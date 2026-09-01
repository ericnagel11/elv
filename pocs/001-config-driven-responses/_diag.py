import os
import dotenv

dotenv.load_dotenv()

import config as cfg
import knowledge
import prompt
import rbac

persona = rbac.DEFAULT_PERSONA
exp = cfg.load_profile("candidate", "production", persona)
scope = knowledge.settings_from_profile(cfg.load_knowledge(cfg.DRAFT_LABEL, "draft", persona))
q = "How long do I have to return something, and is there a fee?"
found = knowledge.search(q, scope, persona)
print("filter:", scope.get("filter"))
print("docs:", [(d["title"], d["status"]) for d in found["documents"]])

inputs = {k: v for k, v in exp.items() if k != "prompt_asset"}
inputs["user_message"] = q
inputs["citation_style"] = scope.get("citation_style", "inline")
inputs["context"] = knowledge.format_context(found["documents"], scope.get("citation_style"))

fm, body = prompt._load_asset("response:v3")
msgs = prompt.render_messages(body, inputs)
print("prompt chars:", sum(len(m["content"]) for m in msgs))

client = prompt._aoai_client()


def probe(label, extra):
    r = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"], messages=msgs, extra_body=extra
    )
    c = r.choices[0]
    u = r.usage
    reasoning = u.completion_tokens_details.reasoning_tokens
    print(
        f"{label:30} finish={c.finish_reason:8} reasoning={reasoning:5} "
        f"visible={u.completion_tokens - reasoning:5} chars={len(c.message.content or '')}"
    )


for i in range(3):
    probe(f"max=2000 run {i + 1}", {"max_completion_tokens": 2000})
for i in range(2):
    probe(
        f"max=2000 effort=low run {i + 1}",
        {"max_completion_tokens": 2000, "reasoning_effort": "low"},
    )
