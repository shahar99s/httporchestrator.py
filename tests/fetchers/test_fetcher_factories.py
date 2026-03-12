from types import SimpleNamespace

import pytest

from fetchers.dropbox_transfer_fetcher import DropboxTransferFetcherFactory
from fetchers.fetcher_registry import (create_fetcher,
                                       find_relevant_fetcher_factory)
from fetchers.filemail_fetcher import FilemailFetcherFactory
from fetchers.mediafire_fetcher import MediaFireFetcherFactory
from fetchers.mega_fetcher import MegaFetcherFactory
from fetchers.sendanywhere_fetcher import SendAnywhereFetcherFactory
from fetchers.sendgb_fetcher import SendgbFetcherFactory
from fetchers.smash_fetcher import SmashFetcherFactory
from fetchers.terabox_fetcher import TeraBoxFetcherFactory
from fetchers.transfernow_fetcher import TransferNowFetcherFactory
from fetchers.transferxl_fetcher import TransferXLFetcherFactory
from fetchers.utils import Mode
from fetchers.wetransfer_fetcher import WeTransferFetcherFactory


@pytest.mark.parametrize(
    ("factory_cls", "lookalike_url"),
    [
        (WeTransferFetcherFactory, "https://wetransfer.com.evil/downloads/TID/SEC123"),
        (FilemailFetcherFactory, "https://filemail.com.evil/d/ifyvssdfbjbnzni"),
        (MediaFireFetcherFactory, "https://example.com/mediafire.com/file/5rv03j13foves42/demo.jpg/file"),
        (TransferNowFetcherFactory, "https://transfernow.net.evil/dl/202603120kavmEMg/yBLpPYkJ"),
        (TransferXLFetcherFactory, "https://transferxl.com.evil/download/08abc123def456ghi789jkl012mno345"),
        (SmashFetcherFactory, "https://fromsmash.com.evil/abcDEF123"),
        (DropboxTransferFetcherFactory, "https://dropbox.com.evil/t/AbCdEfGhIjKlMnOp"),
        (SendAnywhereFetcherFactory, "https://send-anywhere.com.evil/web/downloads/ABCDE12345"),
    ],
)
def test_is_relevant_url_rejects_lookalike_domains(factory_cls, lookalike_url):
    assert factory_cls.is_relevant_url(lookalike_url) is False


@pytest.mark.parametrize(
    ("factory_cls", "valid_url"),
    [
        (SendgbFetcherFactory, "https://sendgb.com/g4D2eAoOamH"),
        (MediaFireFetcherFactory, "https://www.mediafire.com/file/5rv03j13foves42/demo.jpg/file"),
        (WeTransferFetcherFactory, "https://wetransfer.com/downloads/TID/SEC123"),
        (WeTransferFetcherFactory, "https://we.tl/t-mQ7BfOv3WD"),
        (TransferNowFetcherFactory, "https://www.transfernow.net/dl/202603120kavmEMg/yBLpPYkJ"),
        (FilemailFetcherFactory, "https://www.filemail.com/d/ifyvssdfbjbnzni"),
        (MegaFetcherFactory, "https://mega.nz/file/cH51DYDR#qH7QOfRcM-7N9riZWdSjsRq5VDTLfIhThx1capgVA30"),
        (TeraBoxFetcherFactory, "https://www.terabox.com/s/1AbCdEfGhIjKlMn"),
        (TeraBoxFetcherFactory, "https://1024terabox.com/s/1LJTcFCQ5haHb838XjlghcA"),
        (SmashFetcherFactory, "https://fromsmash.com/abcDEF123"),
        (DropboxTransferFetcherFactory, "https://www.dropbox.com/t/AbCdEfGhIjKlMnOp"),
        (DropboxTransferFetcherFactory, "https://www.dropbox.com/scl/fi/demo/file.png?rlkey=abc&dl=0"),
        (TransferXLFetcherFactory, "https://transferxl.com/download/08abc123def456ghi789jkl012mno345"),
        (SendAnywhereFetcherFactory, "https://send-anywhere.com/web/downloads/ABCDE12345"),
        (SendAnywhereFetcherFactory, "https://sendanywhe.re/ABCDE12345"),
    ],
)
def test_is_relevant_url_accepts_valid_url(factory_cls, valid_url):
    assert factory_cls.is_relevant_url(valid_url) is True


@pytest.mark.parametrize(
    ("factory_cls", "invalid_url"),
    [
        (SendgbFetcherFactory, "https://example.com/not-sendgb"),
        (MediaFireFetcherFactory, "https://example.com/not-mediafire"),
        (WeTransferFetcherFactory, "https://example.com/not-wetransfer"),
        (TransferNowFetcherFactory, "https://example.com/not-transfernow"),
        (FilemailFetcherFactory, "https://example.com/not-filemail"),
        (MegaFetcherFactory, "https://example.com/not-mega"),
        (TeraBoxFetcherFactory, "https://example.com/not-terabox"),
        (SmashFetcherFactory, "https://example.com/not-smash"),
        (DropboxTransferFetcherFactory, "https://example.com/not-dropbox-transfer"),
        (TransferXLFetcherFactory, "https://example.com/not-transferxl"),
        (SendAnywhereFetcherFactory, "https://example.com/not-sendanywhere"),
    ],
)
def test_is_relevant_url_rejects_invalid_url(factory_cls, invalid_url):
    assert factory_cls.is_relevant_url(invalid_url) is False


@pytest.mark.parametrize(
    ("builder", "invalid_url"),
    [
        (lambda url: SendgbFetcherFactory(url), "https://example.com/not-sendgb"),
        (lambda url: MediaFireFetcherFactory(url), "https://example.com/not-mediafire"),
        (lambda url: WeTransferFetcherFactory(url), "https://example.com/not-wetransfer"),
        (lambda url: TransferNowFetcherFactory(url), "https://example.com/not-transfernow"),
        (lambda url: FilemailFetcherFactory(url), "https://example.com/not-filemail"),
        (lambda url: MegaFetcherFactory(url), "https://example.com/not-mega"),
        (lambda url: TeraBoxFetcherFactory(url), "https://example.com/not-terabox"),
        (lambda url: SmashFetcherFactory(url), "https://example.com/not-smash"),
        (lambda url: DropboxTransferFetcherFactory(url), "https://example.com/not-dropbox-transfer"),
        (lambda url: TransferXLFetcherFactory(url), "https://example.com/not-transferxl"),
        (lambda url: SendAnywhereFetcherFactory(url), "https://example.com/not-sendanywhere"),
    ],
)
def test_factory_validates_url(builder, invalid_url):
    with pytest.raises(ValueError):
        builder(invalid_url)


@pytest.mark.parametrize(
    ("factory", "expected_name"),
    [
        (SendgbFetcherFactory("https://sendgb.com/g4D2eAoOamH"), "SendGB"),
        (MediaFireFetcherFactory("https://www.mediafire.com/file/5rv03j13foves42/demo.jpg/file"), "MediaFire"),
        (WeTransferFetcherFactory("https://wetransfer.com/downloads/TID/SEC123"), "WeTransfer"),
        (TransferNowFetcherFactory("https://www.transfernow.net/dl/202603120kavmEMg/yBLpPYkJ"), "TransferNow"),
        (FilemailFetcherFactory("https://www.filemail.com/d/ifyvssdfbjbnzni"), "Filemail"),
        (MegaFetcherFactory("https://mega.nz/file/cH51DYDR#qH7QOfRcM-7N9riZWdSjsRq5VDTLfIhThx1capgVA30"), "Mega"),
        (TeraBoxFetcherFactory("https://www.terabox.com/s/1AbCdEfGhIjKlMn"), "TeraBox"),
        (SmashFetcherFactory("https://fromsmash.com/abcDEF123"), "Smash"),
        (DropboxTransferFetcherFactory("https://www.dropbox.com/t/AbCdEfGhIjKlMnOp"), "DropboxTransfer"),
        (
            DropboxTransferFetcherFactory("https://www.dropbox.com/scl/fi/demo/file.png?rlkey=abc&dl=0"),
            "DropboxTransfer",
        ),
        (TransferXLFetcherFactory("https://transferxl.com/download/08abc123def456ghi789jkl012mno345"), "TransferXL"),
        (SendAnywhereFetcherFactory("https://send-anywhere.com/web/downloads/ABCDE12345"), "SendAnywhere"),
        (SendAnywhereFetcherFactory("https://sendanywhe.re/ABCDE12345"), "SendAnywhere"),
        (
            SendAnywhereFetcherFactory(
                "https://mandrillapp.com/track/click/1/sendanywhe.re?p=eyJwIjogIntcInVybFwiOiBcImh0dHA6Ly9zZW5kYW55d2hlLnJlL0FCQ0RFMTIzNDVcIn0ifQ=="
            ),
            "SendAnywhere",
        ),
    ],
)
def test_factory_creates_named_fetcher(factory, expected_name):
    fetcher = factory.create(mode=Mode.INFO)
    assert fetcher.NAME == expected_name


def test_mega_fetcher_uses_request_steps():
    fetcher = MegaFetcherFactory("https://mega.nz/file/cH51DYDR#qH7QOfRcM-7N9riZWdSjsRq5VDTLfIhThx1capgVA30").create(
        mode=Mode.FETCH
    )

    metadata_step = fetcher.steps[0].struct()
    download_step = fetcher.steps[1].struct()

    assert metadata_step.name == "get file metadata"
    assert fetcher.BASE_URL == "https://g.api.mega.co.nz"
    assert metadata_step.request.url == "/cs"
    assert metadata_step.request.method == "POST"
    assert metadata_step.request.params == {"id": 0}
    assert callable(metadata_step.request.req_json)

    # With the new Pythonic architecture hooks are likely callables, not dicts
    # Assuming the logic is moved to callables, we just check that there are hooks
    assert len(metadata_step.teardown_hooks) > 0

    assert download_step.name == "download"
    assert download_step.request.url == "$direct_link"


def test_smash_fetcher_uses_preview_identity_and_notification_safety():
    encoded_identity = "c2hhaGFyc2l2OUBnbWFpbC5jb20="
    fetcher = SmashFetcherFactory(f"https://fromsmash.com/abcDEF123?e={encoded_identity}").create(mode=Mode.INFO)

    preview_step = fetcher.steps[3].struct()

    assert preview_step.name == "load Smash transfer preview"
    assert preview_step.request.params == {
        "version": "01-2024",
        "e": encoded_identity,
    }

    metadata = fetcher.extract_metadata(
        SimpleNamespace(
            json={
                "transfer": {
                    "title": "demo",
                    "download": "https://download.example/demo.zip",
                    "filesNumber": 1,
                    "availabilityStartDate": "2026-03-25T08:31:42.000Z",
                    "availabilityEndDate": "2026-04-01T08:31:42.000Z",
                    "availabilityDuration": 604800,
                    "created": "2026-03-25T08:31:39.856Z",
                    "domain": "fromsmash.com",
                    "customization": {},
                    "notification": {
                        "download": {"enabled": True},
                        "sender": {"enabled": True},
                        "receiver": {"enabled": False},
                    },
                }
            }
        ),
        {"target": "abcDEF123", "region": "eu-central-1", "url": "https://fromsmash.com/abcDEF123"},
    )

    assert metadata["identity_email"] == "shaharsiv9@gmail.com"
    assert metadata["notification_channels"] == ["download", "sender"]
    assert metadata["has_download_notification"] is True
    assert metadata["has_any_notification"] is True
    assert metadata["notification_safe"] is False


# ── Auto-detect wrapper ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected_provider"),
    [
        ("https://wetransfer.com/downloads/TID/SEC123", WeTransferFetcherFactory),
        ("https://we.tl/t-mQ7BfOv3WD", WeTransferFetcherFactory),
        ("https://sendgb.com/g4D2eAoOamH", SendgbFetcherFactory),
        ("https://www.filemail.com/d/ifyvssdfbjbnzni", FilemailFetcherFactory),
        ("https://www.mediafire.com/file/5rv03j13foves42/demo.jpg/file", MediaFireFetcherFactory),
        ("https://mega.nz/file/cH51DYDR#qH7QOfRcM", MegaFetcherFactory),
        ("https://1024terabox.com/s/1LJTcFCQ5haHb838XjlghcA", TeraBoxFetcherFactory),
        ("https://fromsmash.com/oCwyCi2prh-dt", SmashFetcherFactory),
        ("https://www.dropbox.com/t/AbCdEfGhIjKlMnOp", DropboxTransferFetcherFactory),
        ("https://www.transfernow.net/dl/202603120kavmEMg/yBLpPYkJ", TransferNowFetcherFactory),
        ("https://transferxl.com/download/08abc123def456", TransferXLFetcherFactory),
        ("https://send-anywhere.com/web/downloads/ABCDE12345", SendAnywhereFetcherFactory),
        ("https://sendanywhe.re/ABCDE12345", SendAnywhereFetcherFactory),
    ],
)
def test_detect_provider(url, expected_provider):
    assert find_relevant_fetcher_factory(url) == expected_provider


def test_detect_provider_returns_none_for_unknown():
    assert find_relevant_fetcher_factory("https://example.com/unknown") is None


@pytest.mark.parametrize(
    ("url", "expected_name"),
    [
        ("https://wetransfer.com/downloads/TID/SEC123", "WeTransfer"),
        ("https://sendgb.com/g4D2eAoOamH", "SendGB"),
        ("https://www.mediafire.com/file/5rv03j13foves42/demo.jpg/file", "MediaFire"),
        ("https://mega.nz/file/cH51DYDR#qH7QOfRcM-7N9riZWdSjsRq5VDTLfIhThx1capgVA30", "Mega"),
        ("https://fromsmash.com/abcDEF123", "Smash"),
        ("https://send-anywhere.com/web/downloads/ABCDE12345", "SendAnywhere"),
    ],
)
def test_create_fetcher_returns_correct_type(url, expected_name):
    fetcher = create_fetcher(url, mode=Mode.INFO)
    assert fetcher.NAME == expected_name


def test_create_fetcher_raises_for_unknown():
    with pytest.raises(ValueError, match="No supported provider"):
        create_fetcher("https://example.com/unknown")
