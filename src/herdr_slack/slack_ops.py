from slack_sdk.errors import SlackApiError


def _ignore(err: SlackApiError, *codes: str) -> None:
    if err.response.get("error") not in codes:
        raise err


class SlackOps:
    """브리지가 쓰는 Slack 동작(게시, 반응, workspace 채널 준비)."""

    def __init__(self, client, user_id: str):
        self._client = client
        self._user_id = user_id

    def post(self, channel: str, blocks: list[dict], text: str, thread_ts: str | None = None) -> str:
        return self._client.chat_postMessage(channel=channel, blocks=blocks, text=text, thread_ts=thread_ts)["ts"]

    def react(self, channel: str, ts: str, name: str) -> None:
        try:
            self._client.reactions_add(channel=channel, timestamp=ts, name=name)
        except SlackApiError as err:
            _ignore(err, "already_reacted")

    def unreact(self, channel: str, ts: str, name: str) -> None:
        try:
            self._client.reactions_remove(channel=channel, timestamp=ts, name=name)
        except SlackApiError as err:
            _ignore(err, "no_reaction")

    def ensure_channel(self, name: str) -> str:
        """공개 채널을 만들거나 같은 이름의 기존 채널에 참여하고, 사용자를 초대한 뒤 채널 ID를 돌려줌."""
        try:
            channel = self._client.conversations_create(name=name, is_private=False)["channel"]["id"]
        except SlackApiError as err:
            _ignore(err, "name_taken")
            channel = self._find(name)
            self._client.conversations_join(channel=channel)
        try:
            self._client.conversations_invite(channel=channel, users=self._user_id)
        except SlackApiError as err:
            _ignore(err, "already_in_channel", "cant_invite_self")
        return channel

    def _find(self, name: str) -> str:
        cursor = None
        while True:
            res = self._client.conversations_list(types="public_channel", exclude_archived=True, limit=1000,
                                                  cursor=cursor)
            for ch in res["channels"]:
                if ch["name"] == name:
                    return ch["id"]
            cursor = res.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                raise LookupError(f"채널을 찾을 수 없음: {name}")
