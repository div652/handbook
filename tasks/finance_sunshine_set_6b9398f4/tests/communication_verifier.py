#!/usr/bin/env python3
"""Communication-chain verification for the Deal 4821 handoffs."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable


_CUTOFF_DATE = date(2026, 4, 14)
_CUTOFF_TS = datetime(2026, 4, 14, tzinfo=timezone.utc).timestamp()
_DEAL_RE = re.compile(r"\b(?:deal\s*#?\s*)?4821\b", re.IGNORECASE)
_FUNDING_TOPIC_RE = re.compile(
    r"\b(?:fund(?:ing|ed)?|cit|contract(?:s)?\s+in\s+transit|stip(?:ulation)?s?|"
    r"securelink|lender|ally|package|pkg|contract(?:s)?)\b",
    re.IGNORECASE,
)
_TITLE_TOPIC_RE = re.compile(
    r"\b(?:title(?:s|d|\s+work|\s+packet|\s+process(?:ing)?)?|"
    r"registration|dmv|lienholder|lien\s+release)\b",
    re.IGNORECASE,
)

_TARGETS = {
    "funding": {
        "first": "noah",
        "last": "alvarez",
        "email": "noah.alvarez@sunshineandsetauto.com",
    },
    "title": {
        "first": "priya",
        "last": "bennett",
        "email": "priya.bennett@sunshineandsetauto.com",
    },
}
_ACTOR = {
    "first": "jasmine",
    "last": "patel",
    "email": "jasmine.patel@sunshineandsetauto.com",
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(_as_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_as_text(item) for item in value)
    return str(value)


def _person_ids(users: dict[str, Any], person: dict[str, str]) -> set[str]:
    matches: set[str] = set()
    for user_id, raw_user in users.items():
        if not isinstance(raw_user, dict):
            continue
        profile = raw_user.get("profile") or {}
        if not isinstance(profile, dict):
            profile = {}
        identity = " ".join(
            _as_text(value).casefold()
            for value in (
                raw_user.get("name"),
                raw_user.get("real_name"),
                profile.get("display_name"),
                profile.get("real_name"),
                profile.get("email"),
            )
        )
        full_name = f"{person['first']} {person['last']}"
        handle = f"{person['first']}.{person['last']}"
        if person["email"] in identity or handle in identity or full_name in identity:
            matches.add(str(user_id))
    return matches


def _identity_in_text(text: str, target: dict[str, str], target_ids: set[str]) -> bool:
    lowered = text.casefold()
    if target["email"] in lowered:
        return True
    if re.search(
        rf"(?<![\w.])@?{re.escape(target['first'])}(?:[.\s_-]+{re.escape(target['last'])})?(?!\w)",
        lowered,
    ):
        return True
    if re.search(rf"(?<!\w){re.escape(target['last'])}(?!\w)", lowered):
        return True
    return any(f"<@{user_id.casefold()}>" in lowered for user_id in target_ids)


def _message_ts(message: dict[str, Any]) -> float | None:
    raw = message.get("ts")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _iter_workspaces(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        yield from (workspace for workspace in workspaces.values() if isinstance(workspace, dict))
    elif isinstance(workspaces, list):
        yield from (workspace for workspace in workspaces if isinstance(workspace, dict))
    else:
        yield data


def _channel_info(
    channels: dict[str, Any], channel_key: str, messages: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    candidates = {str(channel_key)}
    candidates.update(
        str(message.get("channel"))
        for message in messages
        if message.get("channel") is not None
    )
    for candidate in candidates:
        channel = channels.get(candidate)
        if isinstance(channel, dict):
            return candidate, channel
    for channel_id, raw_channel in channels.items():
        if not isinstance(raw_channel, dict):
            continue
        aliases = {
            str(channel_id),
            str(raw_channel.get("id") or ""),
            str(raw_channel.get("name") or ""),
            str(raw_channel.get("name_normalized") or ""),
        }
        if candidates & aliases:
            return str(channel_id), raw_channel
    return str(channel_key), {}


def _is_public_route(kind: str, channel_key: str, channel: dict[str, Any]) -> bool:
    names = " ".join(
        _as_text(value).casefold()
        for value in (
            channel_key,
            channel.get("id"),
            channel.get("name"),
            channel.get("name_normalized"),
        )
    )
    if kind == "funding":
        return "acct" in names and ("contract" in names or "fund" in names)
    return "acct" in names and "title" in names and "billing" in names


def _channel_members(channel: dict[str, Any]) -> set[str]:
    members = {str(member) for member in channel.get("members") or []}
    if channel.get("user") is not None:
        members.add(str(channel["user"]))
    return members


def _slack_passes(data: dict[str, Any], kind: str) -> str | None:
    target = _TARGETS[kind]
    for workspace in _iter_workspaces(data):
        users = workspace.get("users") or {}
        channels = workspace.get("channels") or {}
        messages_by_channel = workspace.get("messages") or {}
        if not isinstance(users, dict) or not isinstance(channels, dict):
            continue
        if not isinstance(messages_by_channel, dict):
            continue
        target_ids = _person_ids(users, target)
        actor_ids = _person_ids(users, _ACTOR)
        bot_id = workspace.get("bot_user_id")
        if bot_id is not None:
            actor_ids.add(str(bot_id))
        actor_ids.update(
            str(user_id)
            for user_id, raw_user in users.items()
            if isinstance(raw_user, dict) and raw_user.get("is_bot")
        )

        for raw_channel_key, raw_messages in messages_by_channel.items():
            if not isinstance(raw_messages, list):
                continue
            messages = [message for message in raw_messages if isinstance(message, dict)]
            channel_key, channel = _channel_info(channels, str(raw_channel_key), messages)
            is_dm = bool(channel.get("is_im") or channel.get("is_mpim"))
            dm_has_target = is_dm and bool(_channel_members(channel) & target_ids)
            public_route = _is_public_route(kind, channel_key, channel)
            if not public_route and not dm_has_target:
                continue

            by_ts = {
                str(message.get("ts")): message
                for message in messages
                if message.get("ts") is not None
            }
            chains: dict[str, list[dict[str, Any]]] = {}
            for index, message in enumerate(messages):
                root = str(message.get("thread_ts") or message.get("ts") or f"message-{index}")
                chains.setdefault(root, []).append(message)

            for root_ts, chain in chains.items():
                recent = [
                    message
                    for message in chain
                    if (_message_ts(message) is not None and _message_ts(message) >= _CUTOFF_TS)
                ]
                actor_messages = [
                    message for message in recent if str(message.get("user")) in actor_ids
                ]
                if not actor_messages:
                    continue
                recent_text = "\n".join(_as_text(message.get("text")) for message in recent)
                if not _DEAL_RE.search(recent_text):
                    continue
                topic_ok = (
                    public_route
                    if kind == "funding"
                    else bool(_TITLE_TOPIC_RE.search(recent_text))
                )
                if not topic_ok and kind == "funding":
                    topic_ok = bool(_FUNDING_TOPIC_RE.search(recent_text))
                if not topic_ok:
                    continue

                chain_text = "\n".join(_as_text(message.get("text")) for message in chain)
                identity_ok = dm_has_target or _identity_in_text(chain_text, target, target_ids)
                if not identity_ok:
                    root = by_ts.get(root_ts)
                    root_author = str(root.get("user")) if isinstance(root, dict) else ""
                    for message in actor_messages:
                        parent_user_id = str(message.get("parent_user_id") or "")
                        replies_to_root = bool(message.get("thread_ts"))
                        if parent_user_id in target_ids or (
                            replies_to_root and root_author in target_ids
                        ):
                            identity_ok = True
                            break
                if identity_ok:
                    route = "DM" if dm_has_target else channel.get("name") or channel_key
                    return f"Slack {route} chain {root_ts}"
    return None


def _email_date(raw: Any) -> date | None:
    value = _as_text(raw).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError, OverflowError):
            return None


def _email_text(email: dict[str, Any]) -> str:
    return "\n".join(
        _as_text(email.get(field))
        for field in ("subject", "body_text", "body", "snippet")
    )


def _email_recipients(email: dict[str, Any]) -> str:
    return " ".join(
        _as_text(email.get(field)).casefold()
        for field in ("to_addr", "to", "cc_addr", "cc", "bcc_addr", "bcc", "recipients")
    )


def _email_ids(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {item for part in value for item in _email_ids(part)}
    text = _as_text(value).strip().casefold()
    if not text:
        return set()
    bracketed = set(re.findall(r"<[^>]+>", text))
    tokens = set(re.findall(r"[^\s,;]+", text))
    return {token.strip() for token in bracketed | tokens if token.strip()}


def _email_chains(emails: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    parents = list(range(len(emails)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    id_to_indexes: dict[str, set[int]] = {}
    for index, email in enumerate(emails):
        own_ids = _email_ids(email.get("message_id")) | _email_ids(email.get("email_id"))
        thread_ids = _email_ids(email.get("thread_id")) | _email_ids(email.get("conversation_id"))
        for own_id in own_ids:
            id_to_indexes.setdefault(f"message:{own_id}", set()).add(index)
        for thread_id in thread_ids:
            id_to_indexes.setdefault(f"thread:{thread_id}", set()).add(index)

    for indexes in id_to_indexes.values():
        indexes = list(indexes)
        for index in indexes[1:]:
            union(indexes[0], index)

    for index, email in enumerate(emails):
        references = set()
        for field in ("in_reply_to", "references", "reply_to_message_id"):
            references.update(_email_ids(email.get(field)))
        for reference in references:
            for parent_index in id_to_indexes.get(f"message:{reference}", set()):
                union(index, parent_index)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, email in enumerate(emails):
        grouped.setdefault(find(index), []).append(email)
    return list(grouped.values())


def _email_passes(data: dict[str, Any], kind: str) -> str | None:
    target = _TARGETS[kind]
    sent = [
        email
        for email in data.get("emails") or []
        if isinstance(email, dict) and _as_text(email.get("folder")).strip().casefold() == "sent"
    ]
    for chain in _email_chains(sent):
        recent = [email for email in chain if (_email_date(email.get("date")) or date.min) >= _CUTOFF_DATE]
        if not recent:
            continue
        recent_text = "\n".join(_email_text(email) for email in recent)
        if not _DEAL_RE.search(recent_text):
            continue
        topic_re = _FUNDING_TOPIC_RE if kind == "funding" else _TITLE_TOPIC_RE
        if not topic_re.search(recent_text):
            continue
        if not any(target["email"] in _email_recipients(email) for email in chain):
            continue
        chain_id = next(
            (
                _as_text(email.get("thread_id") or email.get("message_id") or email.get("email_id"))
                for email in chain
                if email.get("thread_id") or email.get("message_id") or email.get("email_id")
            ),
            "standalone",
        )
        return f"sent email chain {chain_id}"
    return None


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"{path.name}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path.name}: top-level JSON value is not an object"
    return data, None


def _candidate_path(
    workspace_path: str, external_services_path: str | None, names: tuple[str, ...]
) -> Path | None:
    roots = []
    if external_services_path:
        roots.append(Path(external_services_path))
    roots.append(Path(workspace_path))
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def _verify(kind: str, workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    errors = []
    slack_path = _candidate_path(
        workspace_path, external_services_path, ("slack_data.json", "slack.json")
    )
    if slack_path is not None:
        slack_data, error = _load_json(slack_path)
        if error:
            errors.append(error)
        elif slack_data is not None:
            evidence = _slack_passes(slack_data, kind)
            if evidence:
                return {
                    "pass": True,
                    "score": 1.0,
                    "feedback": f"Verified Deal 4821 {kind} communication via {evidence}; identity and topic are in one chain.",
                }

    mailbox_path = _candidate_path(
        workspace_path, external_services_path, ("mailbox.json", "inbox.json")
    )
    if mailbox_path is not None:
        mailbox_data, error = _load_json(mailbox_path)
        if error:
            errors.append(error)
        elif mailbox_data is not None:
            evidence = _email_passes(mailbox_data, kind)
            if evidence:
                return {
                    "pass": True,
                    "score": 1.0,
                    "feedback": f"Verified Deal 4821 {kind} communication via {evidence}; recipient and topic are in one chain.",
                }

    target = _TARGETS[kind]
    topic = "funding/CIT" if kind == "funding" else "title work"
    suffix = f" Parse errors: {'; '.join(errors)}" if errors else ""
    return {
        "pass": False,
        "score": 0.0,
        "feedback": (
            f"No on/after April 14, 2026 communication chain ties Deal 4821 and {topic} "
            f"to {target['first'].title()} {target['last'].title()} through a valid email recipient, "
            f"Slack DM, correct public channel, body mention, or parent-thread context.{suffix}"
        ),
    }


def verify_funding(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    return _verify("funding", workspace_path, external_services_path)


def verify_title(workspace_path: str, external_services_path: str | None = None) -> dict[str, Any]:
    return _verify("title", workspace_path, external_services_path)
