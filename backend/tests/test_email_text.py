"""Small formatting rules in the provider-facing email text."""

from __future__ import annotations

from types import SimpleNamespace

from app.workflow import emails


def test_subject_names_the_organisation_once() -> None:
    sam = SimpleNamespace(name="Sam Rivera")
    titled = SimpleNamespace(title="Acme Logistics LLC MSA and insurance certificate")
    plain = SimpleNamespace(title="MSA and insurance certificate")
    assert emails.initial_subject(titled, sam, "Acme Logistics LLC") == "Acme Logistics LLC MSA and insurance certificate: request from Sam Rivera"
    assert emails.initial_subject(plain, sam, "Acme Logistics LLC") == "MSA and insurance certificate for Acme Logistics LLC: request from Sam Rivera"


def test_change_notice_bullets_each_request_once() -> None:
    body = emails.provider_update(
        requester=SimpleNamespace(name="Sam Rivera", email="sam@example.com"),
        provider_name="Tom Diaz",
        provider_email="tom@example.com",
        hub_link="https://example.com/u/x",
        changes=["[R-21] Tax provision:", "   New due date: Nov 13, 2026 (was Nov 6, 2026)"],
    )
    assert "  * [R-21] Tax provision:\n     New due date: Nov 13, 2026" in body
    assert "*    New due date" not in body
