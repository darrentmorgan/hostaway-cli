"""Listing image upload and its read-back reconciliation, against mocked routes.

Hostaway queues an image upload and offers no idempotency key, so the POST is
sent once and never retried: what proves an upload landed is reading the listing
back and finding the image on it.  These tests drive that reconciliation — an
upload that lands, one Hostaway accepts and then silently drops, and one whose
outcome the answer never settled.

Every image URL here points at an invented host and no request leaves the test.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError

from hostaway_cli import (
    HostawayListingImage,
    HostawayReadbackError,
    HostawaySession,
    HostawayValidationError,
)
from hostaway_mocks import (
    ACCOUNT_ID,
    BASE_URL,
    SECRET_KEY,
    VILLA_ID,
    mock_access_tokens,
    mock_endpoint,
    ok,
    sent_body,
    villa,
)

IMAGES = f"/listings/{VILLA_ID}/images"
LISTING = f"/listings/{VILLA_ID}"

POOL_URL = "https://images.example.test/villa-saka/pool.jpg"
KITCHEN_URL = "https://images.example.test/villa-saka/kitchen.jpg"


def session() -> HostawaySession:
    return HostawaySession(account_id=ACCOUNT_ID, secret_key=SECRET_KEY, base_url=BASE_URL)


def pool_image() -> HostawayListingImage:
    return HostawayListingImage(url=POOL_URL, caption="Pool at dusk", sort_order=1)


def kitchen_image() -> HostawayListingImage:
    return HostawayListingImage(url=KITCHEN_URL, caption="Kitchen", sort_order=2)


def listing_with(*images: HostawayListingImage, **overrides: Any) -> dict[str, Any]:
    """The invented villa carrying exactly ``images``, as Hostaway returns it."""
    rows = [{"id": 5000 + index, **image.to_wire()} for index, image in enumerate(images, start=1)]
    return villa(listingImages=rows, **overrides)


async def test_an_upload_that_lands_returns_the_listing_carrying_the_image(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    listing = mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(listing_with()), ok(listing_with(pool_image()))],
    )
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({"id": 5001})])

    after = await session().upload_listing_images(VILLA_ID, [pool_image()])

    assert [row["url"] for row in after["listingImages"]] == [POOL_URL]
    assert sent_body(upload) == {
        "images": [{"url": POOL_URL, "caption": "Pool at dusk", "sortOrder": 1}]
    }
    assert len(listing.calls) == 2


async def test_an_image_hostaway_accepts_and_drops_is_reported_not_assumed(
    respx_mock: respx.MockRouter,
) -> None:
    """The upload is accepted, and one of the two images never appears.

    This is the failure the read-back exists for: Hostaway answers success, the
    listing comes back carrying the pool photo and not the kitchen one, and
    without a read-back the operator is told the upload worked.
    """
    mock_access_tokens(respx_mock)
    listing = mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        # The read-back never shows the kitchen image, however long we look.
        steps=[ok(listing_with()), ok(listing_with(pool_image()))],
    )
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({"status": "queued"})])

    with pytest.raises(HostawayReadbackError) as caught:
        await session().upload_listing_images(
            VILLA_ID,
            [pool_image(), kitchen_image()],
            max_readback_attempts=3,
            readback_interval_seconds=0,
        )

    error = caught.value
    assert error.code == "image_upload_not_reconciled"
    assert error.listing_id == VILLA_ID
    detail = error.detail
    assert isinstance(detail, dict)
    assert [row["url"] for row in detail["missing"]] == [KITCHEN_URL]
    # One POST, whatever went wrong: a retried upload duplicates the photo.
    assert len(upload.calls) == 1
    # The first read is the before-read; the three that follow are the attempts.
    assert len(listing.calls) == 4


async def test_a_queue_that_catches_up_on_a_later_read_back_still_succeeds(
    respx_mock: respx.MockRouter,
) -> None:
    """The upload is asynchronous, so the first read-back can be too early."""
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(listing_with()), ok(listing_with()), ok(listing_with(pool_image()))],
    )
    mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({"status": "queued"})])

    after = await session().upload_listing_image(
        VILLA_ID, pool_image(), max_readback_attempts=3, readback_interval_seconds=0
    )

    assert [row["url"] for row in after["listingImages"]] == [POOL_URL]


async def test_an_image_the_listing_already_carries_is_not_posted_again(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(listing_with(pool_image()))])
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({})])

    after = await session().upload_listing_images(VILLA_ID, [pool_image()])

    assert [row["url"] for row in after["listingImages"]] == [POOL_URL]
    assert not upload.called


async def test_only_the_image_the_listing_is_missing_is_posted(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[
            ok(listing_with(pool_image())),
            ok(listing_with(pool_image(), kitchen_image())),
        ],
    )
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({})])

    await session().upload_listing_images(
        VILLA_ID, [pool_image(), kitchen_image()], readback_interval_seconds=0
    )

    assert sent_body(upload) == {
        "images": [{"url": KITCHEN_URL, "caption": "Kitchen", "sortOrder": 2}]
    }


async def test_the_same_url_with_a_different_caption_is_not_a_match(
    respx_mock: respx.MockRouter,
) -> None:
    """A caption still waiting to be corrected must not read as work already done."""
    mock_access_tokens(respx_mock)
    recaptioned = HostawayListingImage(url=POOL_URL, caption="Pool at sunrise", sort_order=1)
    mock_endpoint(
        respx_mock,
        "GET",
        LISTING,
        steps=[ok(listing_with(pool_image())), ok(listing_with(recaptioned))],
    )
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({})])

    await session().upload_listing_images(VILLA_ID, [recaptioned], readback_interval_seconds=0)

    assert sent_body(upload)["images"][0]["caption"] == "Pool at sunrise"


async def test_a_sort_order_read_back_under_hostaway_s_other_name_still_matches(
    respx_mock: respx.MockRouter,
) -> None:
    """``sortOrder`` goes in; ``order`` can come back. Same field, same image."""
    mock_access_tokens(respx_mock)
    row = {"id": 5001, "url": POOL_URL, "caption": "Pool at dusk", "order": 1}
    mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(villa(listingImages=[row]))])
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({})])

    await session().upload_listing_images(VILLA_ID, [pool_image()])

    assert not upload.called


async def test_an_upload_whose_outcome_never_settled_says_so(
    respx_mock: respx.MockRouter,
) -> None:
    """A 503 may have queued the images before failing, so the code says look first."""
    mock_access_tokens(respx_mock)
    mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(listing_with())])
    upload = mock_endpoint(
        respx_mock, "POST", IMAGES, steps=[httpx.Response(503, text="upstream unavailable")]
    )

    with pytest.raises(HostawayReadbackError) as caught:
        await session().upload_listing_images(
            VILLA_ID, [pool_image()], max_readback_attempts=2, readback_interval_seconds=0
        )

    assert caught.value.code == "image_upload_ambiguous"
    assert len(upload.calls) == 1


async def test_an_upload_hostaway_refuses_outright_is_the_typed_error_it_is(
    respx_mock: respx.MockRouter,
) -> None:
    """A 422 queued nothing, so there is nothing to reconcile and no reason to wait."""
    mock_access_tokens(respx_mock)
    listing = mock_endpoint(respx_mock, "GET", LISTING, steps=[ok(listing_with())])
    mock_endpoint(respx_mock, "POST", IMAGES, steps=[httpx.Response(422, text="bad url")])

    with pytest.raises(HostawayValidationError):
        await session().upload_listing_images(VILLA_ID, [pool_image()])

    assert len(listing.calls) == 1


UNUSABLE_IMAGES: dict[str, Any] = {
    "a URL Hostaway cannot fetch": {"url": "villa-saka/pool.jpg"},
    "a file path": {"url": "/var/tmp/pool.jpg"},
    "a negative sort order": {"url": POOL_URL, "sortOrder": -1},
    "a misspelled caption field": {"url": POOL_URL, "airbnb_caption_text": "Pool"},
}


@pytest.mark.parametrize("image", UNUSABLE_IMAGES.values(), ids=UNUSABLE_IMAGES)
async def test_an_image_that_cannot_land_is_refused_before_anything_is_sent(
    respx_mock: respx.MockRouter, image: Any
) -> None:
    """Refused locally, because Hostaway accepts these and then keeps nothing."""
    mock_access_tokens(respx_mock)

    with pytest.raises(ValidationError):
        await session().upload_listing_images(VILLA_ID, [image])

    assert not respx_mock.calls


async def test_an_upload_of_no_images_is_refused_before_anything_is_sent(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)

    with pytest.raises(ValueError, match="at least one image"):
        await session().upload_listing_images(VILLA_ID, [])

    assert not respx_mock.calls


async def test_an_image_given_as_a_mapping_is_validated_like_any_other(
    respx_mock: respx.MockRouter,
) -> None:
    mock_access_tokens(respx_mock)
    mock_endpoint(
        respx_mock, "GET", LISTING, steps=[ok(listing_with()), ok(listing_with(pool_image()))]
    )
    upload = mock_endpoint(respx_mock, "POST", IMAGES, steps=[ok({})])

    await session().upload_listing_images(
        VILLA_ID,
        [{"url": POOL_URL, "caption": "Pool at dusk", "sortOrder": 1}],
        readback_interval_seconds=0,
    )

    assert sent_body(upload) == {
        "images": [{"url": POOL_URL, "caption": "Pool at dusk", "sortOrder": 1}]
    }
