from __future__ import annotations

"""Deterministic intent expansions for service-driven designs.

A small local model should not be required to infer that Discord/Slack/e-mail imply
software notification, networking, and programmable compute. Keep these capability
hints outside the catalog so service names never become fake physical components.
"""

from . import design_intelligence

_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    expansions = [
        (("discord", "dm", "slack", "email", "e-mail", "sms", "text me"), "remote_notification", "Send the requested remote notification in software."),
        (("discord", "slack", "email", "e-mail", "sms", "webhook"), "network_connectivity", "Provide network connectivity for the requested remote service."),
        (("discord", "dm", "slack", "email", "e-mail", "webhook"), "programmable_compute", "Run the event handler and external-service integration."),
    ]
    # Prepend so these high-value exact intents are resolved before broad words such as
    # "message". bootstrap_architecture already deduplicates capabilities.
    design_intelligence._KEYWORD_CAPABILITIES[:0] = expansions
    _INSTALLED = True
