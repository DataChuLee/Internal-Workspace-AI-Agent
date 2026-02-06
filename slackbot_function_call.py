import json
import os

# import anthropic
from dotenv import load_dotenv
from openai import OpenAI
from slack import WebClient
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from calendar_functions import create_event, delete_event, check_event

load_dotenv()

MESSAGES = []

# Event API & Web API
app = App(token=os.environ["SLACK_BOT_TOKEN"])
slack_client = WebClient(os.environ["SLACK_BOT_TOKEN"])
openai_client = OpenAI()
# anthropic_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])


def process_tool_call(tool_name, tool_input):
    if tool_name == "create_event":
        return create_event(**tool_input)
    elif tool_name == "delete_event":
        return delete_event(**tool_input)
    elif tool_name == "check_event":
        return check_event(**tool_input)


# This gets activated when the bot is tagged in a channel
@app.event("app_mention")
def handle_message_events(body, logger):
    # Log message
    print(str(body["event"]["text"]).split(">")[1])

    # Create prompt for ChatGPT
    prompt = str(body["event"]["text"]).split(">")[1]

    # Let the user know that we are busy with the request
    response = slack_client.chat_postMessage(
        channel=body["event"]["channel"],
        thread_ts=body["event"]["event_ts"],
        text="안녕하세요, 개인 비서 슬랙봇입니다! :robot_face: \n곧 전달 주신 문의사항 처리하겠습니다!",
    )
    print(f"\n{'='*50}\nUser Message: {prompt}\n{'='*50}")

    # tools 정의
    tools = [
        {
            "type": "function",
            "function": {
                "name": "create_event",
                "description": "Create a new Calendar Event",
                "parameters": {
                    "type": "object",
                    "required": ["summary", "start", "end"],
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Name of Google Calender Event",
                        },
                        "start": {
                            "type": "string",
                            "description": "Starting date of Google Calender Event in UTC+9 i.e. 2026-02-05T09:00:00+09:00",
                        },
                        "end": {
                            "type": "string",
                            "description": "Ending date of Google Calender Event in UTC+9 i.e. 2026-02-05T10:00:00+09:00",
                        },
                    },
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_event",
                "description": "Check Google Calender Events",
                "parameters": {
                    "type": "object",
                    "required": ["start", "end"],
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Starting date of Google Calender Event in UTC+9 Time i.e. 2024-08-08T09:00:00+09:00",
                        },
                        "end": {
                            "type": "string",
                            "description": "Ending date of Google Calender Event in UTC+9 Time i.e. 2024-08-08T10:00:00+09:00",
                        },
                    },
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_event",
                "description": "Delete a Google Calender Events. Delete immediately if you already have Calendar Event ID",
                "parameters": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique ID of Calender Event. Can be fetched using check_event()",
                        }
                    },
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    ]

    # LLM API 호출
    MESSAGES.append({"role": "user", "content": prompt})
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1024,
        tools=tools,
        messages=MESSAGES,
    )
    message = response.choices[0].message
    finish_reason = response.choices[0].finish_reason
    print(f"finish_reason: {finish_reason}")

    if message.tool_calls:
        MESSAGES.append(message)

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_input = json.loads(tool_call.function.arguments)

            print(f"\nTool Used: {tool_name}")
            print(f"Tool Input: {tool_input}")

            tool_result = process_tool_call(tool_name, tool_input)
            print(f"Tool Result: {tool_result}")

            MESSAGES.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_result),
                }
            )

        # 도구 결과를 포함하여 최종 응답 생성
        final_response = openai_client.chat.completions.create(
            model="gpt-4o-mini", max_tokens=4096, messages=MESSAGES
        )
        final_response = final_response.choices[0].message.content
    else:
        final_response = message.content

    print(f"\nFinal Response: {final_response}")

    # Reply to thread
    response = slack_client.chat_postMessage(
        channel=body["event"]["channel"],
        thread_ts=body["event"]["event_ts"],
        text=f"{final_response}",
    )
    MESSAGES.append({"role": "assistant", "content": final_response})

    return response


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
