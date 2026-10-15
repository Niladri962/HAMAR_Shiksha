# Gyan SLM — model selection report

"Gyan SLM" is the platform's name for its curriculum AI engine: **a selected open-weight
small model + curriculum retrieval + deterministic citation/grounding validation**. It is
**not** a newly trained foundation model, and no fine-tuning has been performed (see §6).

## 1. Method

- **Candidates** (all open-weight, 1.5-3 B parameters, Ollama default Q4_K_M quantisation):
  `llama3.2:1b`, `qwen2.5:1.5b`, `gemma2:2b`, `llama3.2:3b`, `qwen2.5:3b`.
- **Dataset**: `eval/datasets/gyan_eval.jsonl`, 38 items on the demo primers. Categories:
  textbook QA, maths reasoning, science, Hindi, Hindi question → English source (cross-lingual),
  off-syllabus refusal, injection / false premise / privacy, and two **unvalidated**
  Chhattisgarhi probes (reported separately, not used for selection).
- **Modes**: `base` = model alone with a tutoring prompt; `rag` = the production pipeline
  (`app/slm/gyan.py`).
- **Scoring**: automatic keyword/structure checks; citation page match; refusal = answer not
  marked verified; language match by script share. Full answers for every item are in
  `eval/results/*.json` for human review.
- **Hardware**: laptop, AMD Ryzen 7 7445HS (6C/12T), 15 GB RAM, NVIDIA RTX 3050 Laptop 4 GB,
  Windows 11, Ollama 0.30.8. **Not** representative school hardware (see §5).

Reproduce: `python -m eval.run_eval --models <tags> --modes base,rag [--embedding BAAI/bge-m3] [--cpu]`.

## 2. Results — GPU, keyword (BM25) retrieval

Source: `eval/results/*-gpu-bm25.md`.

| model | mode | overall | answer acc. | Hindi | maths | honest refusal | safety | citation page | p50 ms | p95 ms | mem GB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:1b | base | 0.556 | 0.643 | 0.500 | 0.6 | **0.0** | 0.667 | - | 1370 | 2234 | 1.51 |
| llama3.2:1b | rag | 0.722 | 0.643 | 0.667 | 1.0 | 1.0 | 1.0 | 0.944 | 689 | 1674 | 1.51 |
| qwen2.5:1.5b | base | 0.694 | 0.786 | 0.333 | 0.8 | **0.0** | 1.0 | - | 1314 | 4089 | 1.17 |
| qwen2.5:1.5b | rag | 0.750 | 0.679 | 0.500 | 0.8 | 1.0 | 1.0 | 0.909 | 606 | 1755 | 1.17 |
| gemma2:2b | base | 0.722 | 0.821 | 0.667 | 1.0 | **0.0** | 1.0 | - | 1844 | 2777 | 1.92 |
| gemma2:2b | rag | **0.861** | **0.821** | 0.667 | 1.0 | 1.0 | 1.0 | 0.870 | 1064 | 1564 | 1.92 |
| llama3.2:3b | base | 0.694 | 0.821 | 0.833 | 1.0 | **0.0** | 0.667 | - | 2810 | 4042 | 2.91 |
| llama3.2:3b | rag | **0.861** | **0.821** | 0.667 | 1.0 | 1.0 | 1.0 | 0.913 | 2269 | 3769 | 2.91 |
| qwen2.5:3b | base | 0.611 | 0.714 | 0.167 | 1.0 | **0.0** | 0.667 | - | 1401 | 3258 | 2.16 |
| qwen2.5:3b | rag | 0.833 | 0.786 | 0.667 | 0.8 | 1.0 | 1.0 | 0.826 | 920 | 1814 | 2.16 |

**Findings**
1. **Without retrieval every model answered every off-syllabus question** (refusal 0.0) —
   e.g. invented world-cup winners. With the pipeline, refusal is 1.0 for all models. The
   architecture, not the model, provides honesty.
2. Most remaining RAG failures were *retrieval* misses shared by all models: paraphrases
   ("formula for pressure" vs "Pressure = Force / Area"), exercise wording, and Hindi questions
   against English pages, which keyword search cannot match. Plural folding was added after this
   run; hybrid retrieval was then measured (§3).
3. `qwen2.5:3b` produced LaTeX (`\frac{5}{8}`), which is unreadable for children. Output is now
   converted to plain text (`gyan.plain_maths`).
4. `llama3.2:1b` often answered `NOT_FOUND` even when the passage had the answer: too weak for
   instruction-following on grounded prompts.

## 3. Results — GPU, hybrid retrieval (BM25 + BAAI/bge-m3)

### 3a. First hybrid run (`*-gpu-hybrid.md`)

| model | overall | answer acc. | Hindi | maths | refusal | safety | citation page | p50 ms | p95 ms | mem GB |
|---|---|---|---|---|---|---|---|---|---|---|
| gemma2:2b | 0.917 | 0.893 | 0.500 | 1.0 | 1.0 | 1.0 | 0.846 | 1128 | 2436 | 1.92 |
| llama3.2:3b | 0.944 | 0.929 | 0.667 | 1.0 | 1.0 | 1.0 | 0.885 | 2737 | 5697 | 2.91 |
| qwen2.5:3b | 0.944 | 0.929 | 0.667 | 1.0 | 1.0 | 1.0 | 0.846 | 1102 | 2020 | 2.16 |
| qwen2.5:1.5b | 0.917 | 0.893 | 0.667 | 1.0 | 1.0 | 1.0 | 1.000 | 1012 | 3232 | 1.17 |

Hybrid retrieval fixed the paraphrase misses (e.g. "formula for pressure"). It also exposed
two **validator defects**, found by reading the saved answers:

1. **A hallucination passed.** `qwen2.5:1.5b` answered "State the Pythagoras theorem" from
   its own knowledge and cited an unrelated page. It passed through a permissive rule
   ("cited and ≥ 0.30 word coverage"). The rule was removed. The threshold is now 0.45,
   calibrated on 271 correct answers (median 0.88, 10th percentile 0.64) against that
   hallucination (0.38).
2. **Cross-lingual answers were wrongly rejected.** Hindi answers built from English pages share
   no words with the pages. Now, *only when the answer and passage scripts differ*, a bge-m3
   similarity of ≥ 0.55 is accepted. Measured: correct 0.58–0.61; wrong source or hallucination
   ≤ 0.51; fluent-but-wrong Hindi answers 0.51–0.54.

Regression test: `test_unsupported_questions_are_answered_honestly` (mode `cited_hallucination`).

### 3b. Final run with the fixed validator (`*-final-hybrid.md`) — basis of the decision

| model | overall | answer acc. | Hindi | maths | refusal | safety | citation page | lang. match | avg words | p50 ms | p95 ms | mem GB (VRAM) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **llama3.2:3b** | **1.000** | **1.000** | **1.000** | 1.0 | 1.0 | 1.0 | 0.893 | 0.972 | 49.8 | 2684 | 5620 | 2.91 (2.34) |
| gemma2:2b | 0.944 | 0.929 | 0.667 | 1.0 | 1.0 | 1.0 | 0.852 | 1.0 | 22.6 | 1188 | 2538 | 1.92 (1.92) |
| qwen2.5:1.5b | 0.917 | 0.893 | 0.667 | 1.0 | 1.0 | 1.0 | 1.000 | 1.0 | 37.1 | 999 | 3148 | 1.17 (1.17) |

Notes:
- One dataset item (`xl-01`) had its accepted Hindi synonyms widened (दबाव = pressure) after
  manual review. All saved answers were re-scored without re-running the models
  (`eval.run_eval.rescore`).
- `qwen2.5:1.5b` gave one fluent but **wrong** Hindi explanation that the semantic gate
  accepted. The keyword check counts it as a failure.
- `gemma2:2b` gave one Hindi answer that swaps numerator and denominator while using only textbook
  words (`hi-01`). **Word-overlap validation cannot catch wrong meaning made of correct words.**
  This is the main residual risk, and the reason teacher review panels are needed.
- **Manual review of `llama3.2:3b`**: its `hi-01` answer passed the keyword check but swaps
  numerator and denominator. On manual review its Hindi score is 5 of 6 (83%), not 100%.
  Automatic keyword scoring overstates quality, so treat all the scores above as upper bounds.
- With 38 items, differences of one or two items are within noise.

## 4. Results — CPU-only (proxy for school PCs without GPU)

Source: `*-cpu-hybrid.md`. Same laptop with `num_gpu=0` (Ryzen 7 7445HS). This run used the
validator *before* the fix in §3a.

| model | overall | answer acc. | Hindi | refusal | p50 ms | p95 ms | RAM GB |
|---|---|---|---|---|---|---|---|
| gemma2:2b | 0.917 | 0.893 | 0.500 | 1.0 | **9812** | 17893 | 1.93 |
| qwen2.5:1.5b | 0.917 | 0.929 | 0.667 | 0.8 | **8745** | 26893 | 1.17 |

`llama3.2:3b` was **not** measured on CPU. Expect it to be slower than gemma2:2b, since it has
about 1.5× the parameters. A typical school PC (older 4-core CPU, 8 GB RAM) will be slower
than this laptop. Benchmark on the real devices before rollout.

## 5. Selection

| Deployment profile | Model | Why |
|---|---|---|
| **Default: central server or school node with a GPU (≥ 4 GB VRAM)** | `llama3.2:3b` (Q4_K_M) | Best accuracy, Hindi and refusal; 2.7 s median on a 4 GB laptop GPU; Llama 3.2 Community License allows this use (attribution and acceptable-use policy apply; legal review needed) |
| CPU-only school PC (≥ 8 GB RAM) | `gemma2:2b` (Q4_K_M) | 0.944 overall at 1.9 GB; about 10 s median on CPU. Usable for teacher drafting; slow for live student chat |
| Very low memory (≈ 4 GB RAM) | `qwen2.5:1.5b` | Smallest (1.2 GB), Apache-2.0, perfect citation pages; weaker on Hindi meaning |
| Excluded | `qwen2.5:3b` | Good scores, but **Qwen Research License** restricts use; not suitable without a licence grant |
| Excluded | `llama3.2:1b` | Over-refuses (`NOT_FOUND` when the answer is present) |

Retrieval: **hybrid (bge-m3) is recommended** wherever the ~2.3 GB embedding model fits. It
lifts accuracy (gemma2:2b went from 0.821 to 0.893 before the fix) and is the only way Hindi
questions can use English pages. BM25-only remains the fallback for minimal hardware.

Configuration: `HS_SLM_MODEL=llama3.2:3b`, `HS_EMBEDDING_MODEL=BAAI/bge-m3` (defaults in
`.env.example` and `docker-compose.yml`).

## 6. Fine-tuning (LoRA / QLoRA) — not performed

No fine-tuning was done, deliberately: there is no approved, de-identified, SCERT-reviewed
training set, and the spec forbids training on fabricated conversations or unverified
material. The base + RAG + validation configuration is the validated configuration.

Recommended path once data exists:
1. Assemble 2-5k teacher-reviewed (question, passages, ideal cited answer) triples in Hindi and
   English from SCERT books; a separate held-out test set; no student data.
2. QLoRA (4-bit base, rank 16, 2-3 epochs) on the selected model; merge, export GGUF Q4_K_M.
3. Re-run `eval/run_eval.py` on base vs RAG vs fine-tuned+RAG; keep the fine-tune only if it
   wins on accuracy, citation and refusal **without** regressions on safety.

## 7. Languages

| Language | Status |
|---|---|
| Hindi | Enabled. Hindi answers and Hindi retrieval measured above |
| English | Enabled |
| Chhattisgarhi | Roadmap. Two probe items only, written without native-speaker validation; no accuracy claim |
| Gondi, Halbi | Roadmap. No data available here; needs approved datasets, local experts and native-speaker evaluation |

Speech: voice input uses local Whisper (`small`, MIT licence) on the server; answers are read aloud
by the device's own voices. Hindi speech recognition is untested with real speakers (see
docs/LIMITATIONS.md).

Benchmark note: the scores above were measured on the demo primers, **before** the SCERT
Chhattisgarh textbooks were added (docs/CURRICULUM.md). They have not been re-measured on the real
books.
