# Presentation Demo

Run the Day 14 AI Evaluation demo from the repository root:

```bash
python -m pip install -r requirements.txt
python -m streamlit run demo/app.py
```

The app reads saved artifacts by default and does not call the AI model during
the presentation:

- `golden_dataset.json`
- `artifacts/actual_answers.json`
- `artifacts/benchmark_results.json`
- `reflection.md`

If artifacts are missing or do not match the current `golden_dataset.json`, the
UI says so and does not create fake scores.

To create the normal lab artifacts:

```bash
python domain_assistant.py
python evaluate_answers.py
```

`domain_assistant.py` needs `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`.
The optional live run is disabled by default in the UI and runs only one
selected case when explicitly enabled.

Example `.env`:

```bash
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
# Optional for OpenAI-compatible gateways:
OPENAI_BASE_URL=https://api.openai.com/v1
```

Restart Streamlit after changing `.env`.
