@echo off
REM council-review launcher - run the LLM Council on the current project.
REM Uses the llm-council environment but reviews the folder you run it from.
uv run --directory "C:\Users\royn8\.claude\llm-council" python -m backend.review --base-dir "%CD%" %*
