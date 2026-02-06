import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from slack import WebClient
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 사용자 정의 도구 함수들 (기존 파일에서 임포트)
from calendar_functions import create_event, delete_event, check_event
from utils import retrieve_context

load_dotenv()

# 스레드별 대화 내역 저장소
thread_histories = {}

app = App(token=os.environ["SLACK_BOT_TOKEN"])
slack_client = WebClient(os.environ["SLACK_BOT_TOKEN"])
openai_client = OpenAI()

def process_tool_call(tool_name, tool_input):
    """모델이 결정한 도구 이름에 따라 실제 파이썬 함수를 매핑하여 실행합니다."""
    if tool_name == "create_event":
        return create_event(**tool_input)
    elif tool_name == "delete_event":
        return delete_event(**tool_input)
    elif tool_name == "check_event":
        return check_event(**tool_input)
    elif tool_name == "retrieve_context":
        return retrieve_context(**tool_input)
    return {"error": "Tool not found"}

@app.event("app_mention")
def handle_message_events(body, logger):
    event = body["event"]
    thread_ts = event.get("thread_ts", event["ts"])
    
    # 대화 기록 초기화 (멀티턴 설정)
    if thread_ts not in thread_histories:
        thread_histories[thread_ts] = [
            {"role": "system", "content": "당신은 ABC 컴퍼니의 유능한 비서입니다. 제공된 도구를 활용하여 회사 정보 조회 및 캘린더 관리를 수행하세요. 모든 답변은 친절한 한국어로 작성하세요."}
        ]
    
    messages = thread_histories[thread_ts]
    prompt = str(event["text"]).split(">")[1].strip()
    messages.append({"role": "user", "content": prompt})

    # 사용자에게 진행 상황 알림
    slack_client.chat_postMessage(
        channel=event["channel"],
        thread_ts=thread_ts,
        text="요청하신 내용을 처리 중입니다... :robot_face:"
    )

    # 🛠️ 모든 도구(Tools) 정의
    tools = [
        # 1. 회사 정보 조회 (RAG)
        {
            "type": "function",
            "function": {
                "name": "retrieve_context",
                "description": "ABC 컴퍼니의 업무 시간, 복지, 규정 등 회사 관련 내부 정보를 검색합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "조회할 질문 내용"}
                    },
                    "required": ["question"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
        # 2. 일정 생성
        {
            "type": "function",
            "function": {
                "name": "create_event",
                "description": "구글 캘린더에 새로운 일정을 추가합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "일정 제목"},
                        "start": {"type": "string", "description": "시작 시간 (예: 2026-02-05T09:00:00+09:00)"},
                        "end": {"type": "string", "description": "종료 시간 (예: 2026-02-05T10:00:00+09:00)"}
                    },
                    "required": ["summary", "start", "end"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
        # 3. 일정 확인 (조회)
        {
            "type": "function",
            "function": {
                "name": "check_event",
                "description": "특정 기간 내의 구글 캘린더 일정을 조회하여 리스트와 각 일정의 ID를 반환합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "조회 시작 범위 (ISO 형식)"},
                        "end": {"type": "string", "description": "조회 종료 범위 (ISO 형식)"}
                    },
                    "required": ["start", "end"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
        # 4. 일정 삭제
        {
            "type": "function",
            "function": {
                "name": "delete_event",
                "description": "일정 ID를 사용하여 구글 캘린더에서 특정 일정을 삭제합니다.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "삭제할 일정의 고유 ID (check_event를 통해 획득 가능)"}
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        }
    ]

    # LLM 호출
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools
    )
    
    assistant_msg = response.choices[0].message

    # 도구 호출 로직
    if assistant_msg.tool_calls:
        messages.append(assistant_msg) # Assistant의 tool call 기록

        for tool_call in assistant_msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            print(f"Executing: {name} with {args}")
            result = process_tool_call(name, args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": name,
                "content": json.dumps(result)
            })

        # 최종 요약 답변 생성
        final_response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        final_text = final_response.choices[0].message.content
    else:
        final_text = assistant_msg.content

    # 최종 결과 기록 및 전송
    messages.append({"role": "assistant", "content": final_text})
    
    slack_client.chat_postMessage(
        channel=event["channel"],
        thread_ts=thread_ts,
        text=final_text
    )

if __name__ == "__main__":
    print("🚀 모든 도구가 장착된 슬랙 비서가 가동되었습니다!")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()