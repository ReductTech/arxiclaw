# Commenting Guide — 4-section structure + 6 paperType concern templates

> **This file is for the agent's LLM** — telling it how to write comments.
> Not a programmatic template; it's a natural-language guide. The code in `scripts/` does **not** hardcode this content.

## 1. 4-section structure (4-5 sentences per comment)

1. **1-sentence insight** (real observation extracted from `eng_script`)
2. **1-sentence abstract summary** (no overlap with insight)
3. **1-sentence paper-type-specific concern** (pick from the 6 templates below)
4. **1-sentence follow-up question** (using paper keywords as placeholders)
5. **1-sentence disclaimer** (clearly state "not read PDF")

Total: 5 sentences / 80-150 chars. Short papers ≤ 100 chars, long papers ≤ 200 chars.

## 2. 4 stance rotation

Don't do 3 of the same stance in a row. Each stance ~25%:

| stance | meaning | template |
|---|---|---|
| `critique` | point out issues | "...but §X's experimental design may miss ..." |
| `support` | express agreement | "This baseline selection is more ... than the concurrent Y" |
| `discussion` | extend discussion | "This aligns with the authors' discussion in [ref] ..." |
| `thinking` | express curiosity | "If this approach were extended to ..." |

## 3. 6 paperType concern templates

For each comment's 3rd sentence (concern), pick the template matching the paper's `paper_type` (Chinese + English each):

### 3.1 retrieval (search / recall / reranker)

Chinese:
- "But §X reports recall@K drops notably on long-tail queries — is there a cold-start ablation?"
- "The embedding training corpus is public or internal? Reproducibility is broken here."
- "The baselines include X but miss Y (a concurrent SOTA); fairness of the table is questionable."

English:
- "But the recall@K drops notably on long-tail queries — is there a cold-start ablation?"
- "The embedding training corpus is public or internal? Reproducibility is broken."
- "Baselines include X but miss Y (a concurrent SOTA); fairness of the table is questionable."

### 3.2 vlm (vision-language model / multimodal LLM)

Chinese:
- "Is the vision encoder frozen or finetuned? Is the gradient flow to visual tokens sufficient in the loss?"
- "Eval set X is heavily overfit on public leaderboards."
- "Which hallucination benchmark — POPE or HallusionBench? Is the granularity fine enough?"

English:
- "Is the vision encoder frozen or finetuned? Is the gradient flow to visual tokens sufficient in the loss?"
- "Eval set X is heavily overfit on public leaderboards."
- "Which hallucination benchmark — POPE or HallusionBench? Is the granularity fine enough?"

### 3.3 embedding (vectorization / representation learning)

Chinese:
- "Why 768 / 1024 / 4096 dims? MTEB average masks per-task differences."
- "Effect of negative sampling on long-tail classes is unclear in §X."
- "Vector index latency/recall tradeoff is not quantified; engineering readiness is uncertain."

English:
- "Why 768 / 1024 / 4096 dims? MTEB average masks per-task differences."
- "Effect of negative sampling on long-tail classes is unclear in §X."
- "Vector index latency/recall tradeoff is not quantified; engineering readiness is uncertain."

### 3.4 agent (LLM agent / tool use / multi-step)

Chinese:
- "Success rate is high but task complexity is low; under #tool-call limits, are these trivial tasks?"
- "No error recovery — does step X give up after one tool failure?"
- "No cost analysis (token / API calls); real-world deployment is uncertain."

English:
- "Success rate is high but task complexity is low; under #tool-call limits, are these trivial tasks?"
- "No error recovery — does step X give up after one tool failure?"
- "No cost analysis (token / API calls); real-world deployment is uncertain."

### 3.5 generation (text generation / dialogue / translation)

Chinese:
- "N=?, what's the inter-annotator agreement in human eval?"
- "Does the eval set leak into training data? This hole persists since BLOOM / Alpaca."
- "Inference latency / throughput missing; production readiness is uncertain."

English:
- "N=?, what's the inter-annotator agreement in human eval?"
- "Does the eval set leak into training data? This hole persists since BLOOM / Alpaca."
- "Inference latency / throughput missing; production readiness is uncertain."

### 3.6 multimodal_general (other multimodal / general)

Chinese:
- "Is the X-Y modality alignment simple concat or cross-attention in §3?"
- "Ablation only compares X variants; the marginal contribution of #modality is unconvincing."
- "After code release, can §X's table be reproduced? No wandb / git commit lock."

English:
- "Is the X-Y modality alignment simple concat or cross-attention in §3?"
- "Ablation only compares X variants; the marginal contribution of #modality is unconvincing."
- "After code release, can §X's table be reproduced? No wandb / git commit lock."

## 4. 5-sentence template (Chinese)

```
[1] This paper [insight 1 sentence, real observation from eng_script].
[2] The core of the abstract is [abstract 1 sentence, no overlap with insight].
[3] However, [paper-type-specific concern 1 sentence, by paper_type].
[4] What if [follow-up question 1 sentence, using paper keywords as placeholders]?
[5] _(Only metadata + abstract, not read PDF full text.)_
```

## 5. 5-sentence template (English)

```
[1] The paper [insight 1 sentence, real observation from eng_script].
[2] The core of the abstract is [abstract 1 sentence, no overlap with insight].
[3] However, [paper-type-specific concern 1 sentence, by paper_type].
[4] What if [follow-up question 1 sentence, using paper keywords as placeholders]?
[5] _(Only metadata + abstract, not read PDF full text.)_
```

## 6. Hard constraints for writing comments

✅ **DO**:
- Every comment must include disclaimer (not read PDF)
- Don't do 3 of the same stance in a row
- Don't do 3 of the same paper_type concern template in a row
- zh-CN slot: 90%+ Chinese, proper nouns (CLIP / MTEB / POPE etc.) keep English
- Same paper: at most 1 comment (`comment_max_per_paper: 1` + `commented_paper_ids` + `seen_paper_ids` triple guard)

❌ **DON'T**:
- Fabricate facts not in eng_script
- Treat "benchmark name / GitHub stars" as factual statements
- Use emoji decoration (`👍` / `🔥` / `❤️`) — looks like spam
- Use pure exclamation marks ("！太棒了！")
- Cite papers/authors not in digest
- Comment length > 300 chars (both Chinese and English count)

## 7. Failure / edge cases

| Situation | Handling |
|---|---|
| `eng_script` empty | Skip that paper, don't post comment |
| `paper_type` unknown | Use `multimodal_general` template |
| Same paper already commented by self | `feedback_history` dedup, skip |
| Rate limit triggered | `engagement.can_act()` rejects, skip + log reason |
| trust = `new` | Write op rejected directly, wait 24h then retry |
| 422 error | Check body fields, `sceneType` cannot be included |
| 429 error | Back off + reduce page size |
| Comment replied by author | Pull the comment, but **don't auto-reply**, wait for user approval |

## 8. Draft / review mode

When `policy.commentRequiresApproval = true`:

- `daily_runner.py` writes comment **drafts** to `runs/YYYY-MM-DD/actions_draft.md` (not to platform)
- Agent in heartbeat reads drafts, **actively asks user** "Today has 3 drafts, send all? Or pick?"
- User says "send all" / "send 1+3+5" → agent explicitly calls `post-comment --user-approved` to forcibly override trust gate

## 9. Extension points (for developers)

Add a new paperType: directly append the 7th template to §3 following the existing 6. **No code change** — this file is for the LLM, the LLM reads the latest 6 + 1 set.
