import logging
import os
import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from herdr_slack.blocks import agent_list, new_agent_modal
from herdr_slack.bridge import Bridge
from herdr_slack.config import ROOT, load_config, read_env_file
from herdr_slack.herdr import Herdr, HerdrError
from herdr_slack.listener import serve
from herdr_slack.routing import unescape_slack
from herdr_slack.store import ThreadStore

ACTIONS = re.compile(r"^(full|screen|esc|force_send|choice_\d)$")
USAGE = "사용법: `/herdr list` (pane 목록), `/herdr new` (새 에이전트 시작)"

log = logging.getLogger("herdr_slack")


def main() -> None:
    logging.basicConfig(filename=ROOT / "herdr-slack.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", encoding="utf-8")
    cfg = load_config({**read_env_file(), **os.environ})
    app = App(token=cfg.bot_token)

    def post(blocks: list[dict], text: str, thread_ts: str | None = None) -> str:
        return app.client.chat_postMessage(channel=cfg.channel_id, blocks=blocks, text=text,
                                           thread_ts=thread_ts)["ts"]

    bridge = Bridge(Herdr(), ThreadStore(ROOT / "threads.json"), post, cfg.projects_root)

    # 허용된 사용자 1명의 입력만 처리. 나머지는 응답 없이 무시.
    @app.event("message")
    def on_message(event):
        if (event.get("channel") == cfg.channel_id and event.get("user") == cfg.user_id
                and event.get("thread_ts") and not event.get("subtype") and not event.get("bot_id")):
            bridge.handle_reply(event["thread_ts"], unescape_slack(event.get("text", "")))

    @app.action(ACTIONS)
    def on_action(ack, body, action):
        ack()
        if body["user"]["id"] != cfg.user_id:
            return
        msg = body["message"]
        bridge.handle_action(msg.get("thread_ts") or msg["ts"], action["action_id"], action.get("value", ""))

    @app.command("/herdr")
    def on_command(ack, command, client, respond):
        ack()
        if command["user_id"] != cfg.user_id:
            return
        sub = command.get("text", "").strip().split(" ", 1)[0]
        if sub == "list":
            try:
                respond(blocks=agent_list(Herdr().list_agents()), text="pane 목록")
            except HerdrError as err:
                respond(text=f"⚠️ herdr 오류: {err}")
        elif sub == "new":
            client.views_open(trigger_id=command["trigger_id"], view=new_agent_modal())
        else:
            respond(text=USAGE)

    @app.view("new_agent")
    def on_new_agent(ack, body, view):
        if body["user"]["id"] != cfg.user_id:
            ack()
            return
        values = view["state"]["values"]
        name = (values["name"]["value"]["value"] or "").strip()
        kind = values["kind"]["value"]["selected_option"]["value"]
        prompt = values["prompt"]["value"].get("value") or ""
        try:
            bridge.check_new(name)
        except ValueError as err:
            ack(response_action="errors", errors={"name": str(err)})
            return
        ack()  # Slack은 3초 안에 응답을 요구. 에이전트 시작은 그 뒤에 진행.
        try:
            result = bridge.start_new(name, kind, prompt)
        except Exception as err:
            log.exception("새 에이전트 시작 실패")
            result = f"⚠️ 새 에이전트 시작 실패: {str(err)[:1000]}"
        post([{"type": "section", "text": {"type": "mrkdwn", "text": result}}], result)

    serve(cfg.event_port, bridge.on_status_event)
    log.info("시작 (훅 이벤트 포트 %d)", cfg.event_port)
    SocketModeHandler(app, cfg.app_token).start()
