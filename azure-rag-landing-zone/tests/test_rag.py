import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "evals"))

from rag.api import create_app  # noqa: E402
from rag.chunking import chunk_markdown, load_docs  # noqa: E402
from rag.clients import HashEmbedder, InMemoryRetriever, tokens  # noqa: E402
from rag.config import Settings  # noqa: E402
from rag.pipeline import REFUSAL, build_pipeline  # noqa: E402
import run_eval  # noqa: E402

DOCS = ROOT / "data" / "docs"


def test_chunking_keeps_headings_as_titles():
    chunks = chunk_markdown("# Doc\nintro\n## Part A\nalpha text\n## Part B\nbeta text", "doc.md")
    assert [c.title for c in chunks] == ["Doc", "Part A", "Part B"]
    assert len({c.id for c in chunks}) == 3


def test_long_sections_are_split_with_overlap():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_markdown(f"# Big\n{body}", "big.md", max_chars=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c.content) <= 500 + 100 + 400 for c in chunks)


def test_stemming_matches_inflections():
    assert tokens("approves activations") == tokens("approved activation")
    assert tokens("applies") == tokens("apply")


def test_retriever_finds_the_right_document():
    emb = HashEmbedder()
    retriever = InMemoryRetriever(load_docs(DOCS), emb)
    hits = retriever.search("PIM activation duration", emb.embed(["PIM activation duration"])[0], 3)
    assert hits[0].chunk.source == "production-access.md"


def test_answer_is_cited_and_grounded():
    answer = build_pipeline(Settings(mode="local", docs_dir=DOCS)).answer("What is the RPO for tier-1 services?")
    assert "15 minutes" in answer.answer
    assert answer.citations and answer.citations[0].source == "backup-and-restore.md"


def test_out_of_scope_question_is_refused():
    answer = build_pipeline(Settings(mode="local", docs_dir=DOCS)).answer("Who won the football league last season?")
    assert answer.answer == REFUSAL
    assert answer.citations == []


def test_api_chat_endpoint():
    client = TestClient(create_app(build_pipeline(Settings(mode="local", docs_dir=DOCS))))
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.post("/chat", json={"question": "How do I roll back a deployment on AKS?"})
    assert r.status_code == 200 and "revert the pull request" in r.json()["answer"].lower()
    assert client.post("/chat", json={"question": "x"}).status_code == 422


def test_eval_gate_passes_on_baseline_and_fails_on_stricter_thresholds():
    golden = run_eval.load_golden(ROOT / "evals" / "golden.jsonl")
    metrics, _ = run_eval.evaluate(golden, run_eval.ask_inprocess())
    thresholds = json.loads((ROOT / "evals" / "thresholds.json").read_text())
    assert run_eval.check(metrics, thresholds) == []
    assert run_eval.check(metrics, {**thresholds, "answer_recall": 1.0})  # one known miss in the baseline
