"""Run six questions against the real server and export results for manual review."""

from pathlib import Path

from config import GUIDE_PATH, OLLAMA_BASE_URL
from rag import RAGError, build_index, generate, retrieve

CASES = [
    ("Answerable", "Where is the Saigon Central Post Office?", "G03"),
    ("Answerable", "Where does Nguyen Hue Walking Street run from and to?", "G06"),
    ("Answerable", "Which months are usually the dry season in Ho Chi Minh City?", "G12"),
    ("Paraphrase", "What is the street address of the post office opposite Notre Dame Cathedral?", "G03"),
    ("Outside the guide", "How much is admission to the War Remnants Museum?", "None"),
    ("Outside the guide", "Will it rain in Ho Chi Minh City tomorrow?", "None"),
]


def main():
    try:
        records, vectors = build_index(GUIDE_PATH.read_text(encoding="utf-8"), OLLAMA_BASE_URL)
        lines = [
            "# Live-server test results",
            "",
            "Review each answer and complete correctness and failure stage. Valid citations do not prove correctness.",
            "",
            "| Question | Type | Expected entry ID | Retrieved IDs | Correct? | Failure stage |",
            "|---|---|---|---|---|---|",
        ]
        answers = []
        for number, (kind, question, expected) in enumerate(CASES, 1):
            print(f"Running question {number}/{len(CASES)}...", flush=True)
            hits = retrieve(question, records, vectors, OLLAMA_BASE_URL)
            actual = ", ".join(h["id"] for h in hits)
            try:
                answer = generate(question, hits, OLLAMA_BASE_URL)
                status, failure = "Needs manual review", ""
            except RAGError as error:
                answer = str(error)
                status, failure = "Runtime error", error.stage or "Connection/generation"
            lines.append(f"| {question} | {kind} | {expected} | {actual} | {status} | {failure} |")
            scores = ", ".join(f"{h['id']}={h['score']:.4f}" for h in hits)
            answers.append(f"## Question {number}\n\n{question}\n\n{answer}\n\nScores: {scores}\n")
        output = Path(__file__).with_name("test_results.md")
        output.write_text("\n".join(lines) + "\n\n" + "\n".join(answers), encoding="utf-8")
        print(f"Saved {output.name}. Review the answers and update the table in README.md.")
    except (RAGError, OSError) as error:
        raise SystemExit(f"Cannot run the evaluation: {error}") from None


if __name__ == "__main__":
    main()

