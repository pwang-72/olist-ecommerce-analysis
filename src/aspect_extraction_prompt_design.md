# Aspect Extraction Prompt: Design Rationale

This document walks through the extraction prompt section by section, explaining the reasoning behind each part. It's meant to sit alongside the prompt as a record of *why* it looks the way it does, for a project built on the Olist Brazilian e-commerce reviews aiming at a per-aspect rating system rather than a single overall star rating.

---

## Background

```markdown
You are extracting evaluative content from Brazilian Portuguese e-commerce
product reviews, for a per-aspect rating system covering the product, the
seller, and the delivery experience.
```

**Rationale**

The first approach tried was zero-shot classification with an offline NLI model (`facebook/bart-large-mnli`), which performed poorly. This wasn't simply a weak-model problem — it was a task-shape mismatch. Zero-shot NLI classification works by testing whether a review "entails" a hypothesis like *"this text is about delivery"*; that's a topic-relatedness judgment, not a sentiment or evaluation judgment, and no amount of tuning the candidate labels would make it recognize negation, discourse structure, or which of several topics mentioned in one sentence the reviewer is actually praising or complaining about. An LLM did substantially better because the task genuinely requires reading comprehension and pragmatic reasoning about what a reviewer is claiming, not pattern-matching against topic labels.

Before settling on an extraction approach, ~2,000 reviews were embedded and explored by sampling a review alongside its nearest neighbors in embedding space, using a rough, offline, bulk English machine translation purely so the reviews could be read and compared without needing Portuguese fluency. That was an exploratory step for discovering what aspects recur in the data — not part of the extraction pipeline itself — and it's where the aspect vocabulary below originates (see OUTPUT FIELDS).

The extraction pipeline itself runs on the original Portuguese text, not a translation, for two reasons. First, the LLM already handles Portuguese well on its own, so translating first adds a step with no compensating benefit. Second, and more importantly, machine translation isn't risk-free for exactly the phenomena this prompt exists to handle: negation scope and discourse connectives ("mas", "embora", and similar) are precisely the kind of thing translation can subtly mishandle, so translating first risks quietly reintroducing the same fragility that the DISCOURSE ROLE design (below) exists to fix — just relocated into an earlier, less visible step. Keeping the LLM on the source language keeps that risk out of the pipeline.

For the same reason, the few-shot examples inside the prompt are in Portuguese rather than English: in-context examples work best when they match the language and register the model will actually see at inference time. English glosses are kept alongside the examples in project documentation purely as an audit aid for a non-Portuguese-reading analyst — not a claim that the model benefits from seeing English.

---

## SELECTION

```markdown
### SELECTION — what counts as a span worth extracting

A span is evaluative if substituting it for its negation or a contrasting
alternative would change your assessment of some aspect of the purchase.
This includes explicit evaluative language ("péssimo", "excelente", "com
defeito") and implicit evaluative content: factual statements with strong
evaluative implicature even without sentiment words ("quebrou depois de
dois dias" implies a durability complaint on its own).

Do NOT extract:

- Pure narrative or circumstantial background (why they bought it, who
  it's for, when they ordered) — these fail the substitution test.
- Hypothetical or conditional statements about the future ("se quebrar de
  novo, vou devolver") — nothing is asserted about the realized experience.
- Opinions explicitly attributed to someone other than the reviewer,
  unless the reviewer endorses the claim as their own.
- Text that merely names, mentions, or describes an aspect without
  evaluating it.
```

**Rationale**

The central decision here is that *evaluative content*, not topic relevance, defines a worthwhile span — the direct fix for the original failure mode. An approach built around topic (does this text mention delivery?) will pick up any sentence referencing an aspect, whether or not the reviewer is actually passing judgment on it. The substitution test — would negating or contrasting this span change your assessment of the aspect it concerns — targets evaluative *function* instead of topic *presence*, and it's deliberately agnostic to whether the evaluative content is explicit (a sentiment word) or only implied by a fact: "broke after two days" implies a durability complaint with zero sentiment vocabulary present.

Four categories are excluded, each failing that test in a specific, recurring way:

- **Pure narrative or circumstantial background** fails the test outright. *"I bought this for my daughter's birthday"* doesn't become a different claim about the product if negated — it isn't evaluating anything.
- **Hypothetical or conditional statements about the future** — nothing has happened yet to evaluate. *"If it breaks again, I'll return it"* asserts a contingent future action, not a judgment about the realized experience.
- **Opinions attributed to someone other than the reviewer** — the rating system should reflect the reviewer's own assessment. *"My husband said the smell was off, but I didn't notice anything"* — the husband's reaction isn't the reviewer's endorsed view, and counting it would attribute an opinion to the wrong person.
- **Text that merely names or describes an aspect without evaluating it** — a catch-all for cases that don't fit the three categories above but still amount to mention without judgment, e.g. *"the box was a plain brown box"*: descriptive, not evaluative, even though it names a concrete aspect (packaging).

---

## OUTPUT FIELDS — text and aspect

```markdown
### OUTPUT FIELDS

For each extracted span, output exactly these fields:

- **text**: the minimal span itself — the words doing the evaluative work,
  not the whole sentence and not the connective joining it to anything else.

- **aspect**: a short, specific snake_case label for what is being
  evaluated. Use one of the following labels:

  - "overall_satisfaction"
  - "product_quality"
  - "product_condition_damage"
  - "product_completeness"
  - "product_color_accuracy"
  - "product_description_accuracy"
  - "product_appearance"
  - "wrong_item_shipped"
  - "packaging"
  - "delivery_timing"
  - "delivery_non_receipt"
  - "price"
  - "seller_contact"
  - "seller_service"
  - "others"

  Use the most specific applicable predefined aspect whenever one fits.

  Use "overall_satisfaction" only when one review evaluates the overall
  purchase or experience with no specific aspect. Otherwise classify the
  specific aspect and neglect "overall_satisfaction".

  Use "others" only when the text is genuinely evaluative but the
  evaluated aspect does not fit any of the predefined categories above.
  Do not use "others" merely because you are uncertain which predefined
  aspect applies. If a predefined aspect reasonably fits, use that aspect
  instead. Do not use "others" for non-evaluative text. Non-evaluative
  text should not be extracted as a span.

  "product_quality" refers to the intrinsic performance, durability,
  functionality, and reliability of the product during use, whereas
  "product_condition_damage" refers specifically to the physical state of
  the product upon arrival, including damage, defects, or breakage
  present at delivery.

  When multiple predefined aspects could apply, choose the most specific
  one according to the definitions above.
```

**Rationale**

The aspect vocabulary was built empirically, not derived from a theory of what e-commerce reviews should contain. It's summarized from the same embedding-neighbor exploration mentioned above: reading through sampled reviews alongside their nearest neighbors surfaced recurring, distinguishable themes — a defect is a different complaint from damage in transit, which is different again from packaging condition or an outright wrong item — and those became the candidate labels, later trimmed and named into this fixed list.

The labels are deliberately more granular than the three broad buckets the rating system ultimately cares about (product, seller, delivery). Classifying directly into three broad categories invites the same shortcut this whole prompt exists to avoid: *"the seller sent the wrong product"* contains the word "product," and a model working only with broad categories has a real incentive to default to `product_quality` rather than doing the harder inference that this is a seller fulfillment failure. A more specific, more textually literal label (`wrong_item_shipped`) is an easier, less inference-heavy call, and the mapping from fine label to whatever broad category a final report needs becomes a separate, deterministic, auditable step — not a judgment silently made once, inside the extraction itself, with no record of why.

Two labels are special-cased. `overall_satisfaction` is reserved for genuinely global, undifferentiated evaluations with no more specific aspect to point to — *"I love it!"* with nothing further said about what, specifically — and it explicitly loses to any more specific label when one applies; it's a fallback for terse reviews, not a default for uncertainty. `others` is a safety valve for spans that are genuinely evaluative but don't fit any predefined category, and it's deliberately hard to reach for the same reason: without a real constraint on it, `others` would quietly absorb every case the model finds difficult, defeating the purpose of having specific labels at all.

This list is a property of this dataset and this project's questions, not a fixed ontology. A different product mix, a different marketplace, or different analytical priorities would likely call for a different, if overlapping, set of labels — it's meant to be revisited as the data warrants, not treated as settled.

---

## OUTPUT FIELDS — attitude, discourse_role, relation

```markdown
- **attitude**: `"positive"`, `"negative"`, or `"neutral"`.

  - `"positive"`: expresses approval, satisfaction, or favorable
    evaluation of the aspect.
  - `"negative"`: expresses disapproval, dissatisfaction, or unfavorable
    evaluation of the aspect.
  - `"neutral"`: evaluates the aspect without a clear positive or
    negative orientation, or expresses mixed/ambivalent evaluation that cannot be cleanly separated.

- **discourse_role**: `"nucleus"`, `"satellite"`, or `"none"`.

- **relation**: `"concession_exclusion"`, `"concession_tradeoff"`, or
  `"none"`. Always use `"none"` unless `discourse_role` is `"satellite"`.
```

**Rationale**

`attitude` captures the polarity of an evaluative span after the selection stage has established that the span is genuinely evaluative. `neutral` is therefore not a fallback for non-evaluative text. Instead, `neutral` is reserved for cases in which the span makes an evaluative assessment but the assessment itself has no clearly positive or negative orientation. 

`discourse_role` and `relation` are where the harder reasoning lives, and they get their own section next.

---

## DISCOURSE ROLE

```markdown
### DISCOURSE ROLE — when to mark a span as a subordinate satellite

Most evaluative spans get discourse_role "none": they're independent
points, even when another evaluative span about a different aspect sits
right next to them in the same sentence, and even when they're joined by
a contrastive connective. "O produto é lindo, mas a cor é completamente
diferente da da foto" — beauty and color-accuracy are separate points in
tension, neither serving the other; both stay "none".

Mark a pair as nucleus/satellite instead only when one clause is a minor
or explanatory point that exists to qualify, excuse, or soften the
other's claim, rather than standing as its own separate observation.

Once a pair is asymmetric, which clause is which follows the connective
mechanically, not a case-by-case judgment call:

- Coordinating contrastives (mas, porém, contudo, no entanto — but,
  however, yet): the clause AFTER the connective is the nucleus; the
  clause/sentence before it is the satellite.
- Subordinating concessives (embora, apesar de, mesmo que — although,
  despite, even though): the clause INTRODUCED BY the connective is
  always the satellite, regardless of where it falls in the sentence —
  even if it comes first or is embedded mid-sentence.

- concession_exclusion: the satellite rules out an alternative
  explanation for a problem the nucleus asserts. "O produto tem um
  defeito" invites "talvez tenha sido a entrega" — "nada veio quebrado"
  answers exactly that, so it's concession_exclusion.
- concession_tradeoff: the satellite is a real but minor evaluation the
  reviewer concedes on the way to an overall verdict in the nucleus, or
  reassurance that a problem asserted in the nucleus didn't extend to a
  different aspect. "um pouco caro" conceded in favor of "vale a pena";
  "produto intacto" conceded alongside "caixa danificada".

Check the connective structure: causal connectives ("porque") or
conditionals ("se") typically signal non-concessive relations and should
be handled via exclusion criteria rather than discourse role assignment,
since such clauses are often not independently evaluative.
```

**Rationale**

The motivating failure case for this whole axis was a review along the lines of *"nothing was broken when it arrived, yet the product clearly has a defect."* A naive extractor risks reading "broken"/"arrived" as a signal about delivery, when the reviewer is actually using that clause to rule out shipping damage as the explanation for a defect they're attributing to the product itself — the clause is doing work in service of a different, more central claim, not standing as its own statement about delivery.

The theoretical grounding for handling this is Rhetorical Structure Theory (Mann & Thompson, 1988), which describes text as organized into nucleus–satellite pairs: a nucleus carries the primary communicative point, and a satellite is subordinate material connected to it by a named relation. RST provided a principled way to split what had originally been one confounded judgment — "is this comment-worthy" — into two independent facts about a span: whether it's evaluative at all (a property of the clause on its own, the `attitude` field) and how it relates structurally to other clauses in the same review (a property of the *relationship between* clauses — `discourse_role` and `relation`). Treating those as one variable was the original mistake; a clause can be genuinely evaluative and still be rhetorically subordinate, which is exactly the "nothing was broken" case.

RST's full relation inventory is much larger than what's used here. Working through the candidates relevant to reviews — Background/Circumstance, Concession (trade-off), Concession (exclusion), Evidence/Justify, Condition/hypothetical, Comparison, Attribution — only `concession_exclusion` and `concession_tradeoff` earn a place in the schema. The other five don't need one, because SELECTION (above) already removes them before discourse-role assignment would ever apply:

- **Background/Circumstance** is, by definition, non-evaluative — it's the first category SELECTION excludes, so it never becomes a candidate span.
- **Evidence/Justify** (*"I've bought electronics for ten years, and this is the worst"*) is typically non-evaluative too — the credibility-building clause isn't evaluating the current product — so it's filtered the same way.
- **Condition/hypothetical** and **Attribution** are excluded by name in SELECTION's own list.
- **Comparison** (*"better than the one I bought last year"*) is usually captured within a single evaluative span's attitude judgment rather than needing a second, related span at all.

What's left over — content that passes SELECTION (so it's genuinely evaluative) *and* is still rhetorically subordinate to a different claim — is a narrow category, and it splits cleanly into two patterns: `concession_exclusion`, where the satellite rules out an alternative explanation for a problem the nucleus asserts, and `concession_tradeoff`, where the satellite is a real but minor point conceded on the way to an overall verdict in the nucleus. That five of seven candidate relations turn out to be redundant with SELECTION, rather than needing their own handling, is worth noting on its own: this axis stays narrow because most of the work is already done upstream, not because the taxonomy was arbitrarily trimmed.

---

## OUTPUT FORMAT

```markdown
### OUTPUT FORMAT

Return:

{"spans": [...]}

If no evaluative content exists, return:

{"spans": []}
```

**Rationale**

Purely mechanical — this section fixes the JSON shape the fields need to come back in, including the empty-review case, so output can be parsed reliably at scale. It isn't a modeling decision the way the sections above are, so it doesn't carry independent rationale beyond that.

---

## EXAMPLES

```markdown
Review: "Nada veio quebrado, mas o produto claramente tem um defeito."
(Nothing arrived broken, but the product clearly has a defect.)
Output:
[
  {"text": "Nada veio quebrado", "aspect": "product_condition_damage", "attitude": "positive", "discourse_role": "satellite", "relation": "concession_exclusion"},
  {"text": "o produto claramente tem um defeito", "aspect": "product_quality", "attitude": "negative", "discourse_role": "nucleus", "relation": "none"}
]

Review: "O preço é um pouco alto, mas vale a pena."
(The price is a bit high, but it's worth it.)
Output:
[
  {"text": "O preço é um pouco alto", "aspect": "price", "attitude": "negative", "discourse_role": "satellite", "relation": "concession_tradeoff"},
  {"text": "vale a pena", "aspect": "overall_satisfaction", "attitude": "positive", "discourse_role": "nucleus", "relation": "none"}
]

Review: "A cor é linda. A entrega foi rápida."
(The color is lovely. The delivery was fast.)
Output:
[
  {"text": "A cor é linda", "aspect": "product_appearance", "attitude": "positive", "discourse_role": "none", "relation": "none"},
  {"text": "A entrega foi rápida", "aspect": "delivery_timing", "attitude": "positive", "discourse_role": "none", "relation": "none"}
]

Review: "Comprei para o aniversário da minha filha."
(I bought it for my daughter's birthday.)
Output:
[]
```

**Rationale**

The four worked examples aren't arbitrary illustrations — each anchors a specific decision boundary that testing showed was genuinely error-prone, which is the point of including them at all. Abstract instructions are necessary but not sufficient for a task this pragmatically subtle: a model can be told in the abstract that negation and rhetorical subordination matter and still misapply that rule on a specific sentence, because applying it requires resolving real ambiguity (is this connective signaling concession, or just contrast?) that's easier to demonstrate than to fully specify in words. Concrete worked examples let the model generalize from a pattern rather than parse a rule — this is the core idea behind few-shot prompting, and it's why the examples carry real instructional weight rather than being decorative.

Each one covers a distinct boundary:

- *Nada veio quebrado, mas o produto claramente tem um defeito* anchors `concession_exclusion` — the original motivating failure.
- *O preço é um pouco alto, mas vale a pena* anchors `concession_tradeoff`, establishing that it's a distinct pattern from the first, not a duplicate.
- *A cor é linda. A entrega foi rápida* anchors the default case: two independent evaluative spans, no subordination, `discourse_role` stays `"none"` for both — the common case, so the model doesn't over-apply the concession machinery.
- *Comprei para o aniversário da minha filha* anchors outright rejection: an empty output, showing what SELECTION excludes entirely rather than tags and discounts.
