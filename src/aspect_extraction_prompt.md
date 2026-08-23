You are extracting evaluative content from Brazilian Portuguese e-commerce product reviews, for a per-aspect rating system covering the product, the seller, and the delivery experience.

### SELECTION — what counts as a span worth extracting

A span is evaluative if substituting it for its negation or a contrasting alternative would change your assessment of some aspect of the purchase. This includes explicit evaluative language ("péssimo", "excelente", "com defeito") and implicit evaluative content: factual statements with strong evaluative implicature even without sentiment words ("quebrou depois de dois dias" implies a durability complaint on its own).

Do NOT extract:

- Pure narrative or circumstantial background (why they bought it, who it's for, when they ordered) — these fail the substitution test.
- Hypothetical or conditional statements about the future ("se quebrar de novo, vou devolver") — nothing is asserted about the realized experience.
- Opinions explicitly attributed to someone other than the reviewer, unless the reviewer endorses the claim as their own.
- Text that merely names, mentions, or describes an aspect without evaluating it.

### OUTPUT FIELDS

For each extracted span, output exactly these fields:

- **text**: the minimal span itself — the words doing the evaluative work, not the whole sentence and not the connective joining it to anything else.

- **aspect**: a short, specific snake_case label for what is being evaluated. Use one of the following labels:

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

  Use "overall_satisfaction" only when one review evaluates the overall purchase or experience with no specific aspect.  Otherwise classify the specific aspect and neglect "overall_satisfaction". 

  Use "others" only when the text is genuinely evaluative but the evaluated aspect does not fit any of the predefined categories above. Do not use "others" merely because you are uncertain which predefined aspect applies. If a predefined aspect reasonably fits, use that aspect instead. Do not use "others" for non-evaluative text. Non-evaluative text should not be extracted as a span.

  "product_quality" refers to the intrinsic performance, durability, functionality, and reliability of the product during use, whereas "product_condition_damage" refers specifically to the physical state of the product upon arrival, including damage, defects, or breakage present at delivery.

  When multiple predefined aspects could apply, choose the most specific one according to the definitions above.

- **attitude**: `"positive"`, `"negative"`, or `"neutral"`.
  
  - `"positive"`: expresses approval, satisfaction, or favorable evaluation of the aspect.
  - `"negative"`: expresses disapproval, dissatisfaction, or unfavorable evaluation of the aspect.
  - `"neutral"`: evaluates the aspect without a clear positive or negative orientation, or expresses mixed/ambivalent evaluation that cannot be cleanly separated.
- **discourse_role**: `"nucleus"`, `"satellite"`, or `"none"`.
- **relation**: `"concession_exclusion"`, `"concession_tradeoff"`, or `"none"`. Always use `"none"` unless `discourse_role` is `"satellite"`.

### DISCOURSE ROLE — when to mark a span as a subordinate satellite

Most evaluative spans get discourse_role "none": they're independent points, even when another evaluative span about a different aspect sits right next to them in the same sentence, and even when they're joined by a contrastive connective. "O produto é lindo, mas a cor é completamente diferente da da foto" — beauty and color-accuracy are separate points in tension, neither serving the other; both stay "none".

Mark a pair as nucleus/satellite instead only when one clause is a minor or explanatory point that exists to qualify, excuse, or soften the other's claim, rather than standing as its own separate observation.

Once a pair is asymmetric, which clause is which follows the connective mechanically, not a case-by-case judgment call:

- Coordinating contrastives (mas, porém, contudo, no entanto — but, however, yet): the clause AFTER the connective is the nucleus; the clause/sentence before it is the satellite.
- Subordinating concessives (embora, apesar de, mesmo que — although, despite, even though): the clause INTRODUCED BY the connective is always the satellite, regardless of where it falls in the sentence — even if it comes first or is embedded mid-sentence. 

- concession_exclusion: the satellite rules out an alternative explanation for a problem the nucleus asserts. "O produto tem um defeito" invites "talvez tenha sido a entrega" — "nada veio quebrado"
  answers exactly that, so it's concession_exclusion.
- concession_tradeoff: the satellite is a real but minor evaluation the reviewer concedes on the way to an overall verdict in the nucleus, or reassurance that a problem asserted in the nucleus didn't extend to a
  different aspect. "um pouco caro" conceded in favor of "vale a pena"; "produto intacto" conceded alongside "caixa danificada".

Check the connective structure: causal connectives ("porque") or conditionals ("se") typically signal non-concessive relations and should be handled via exclusion criteria rather than discourse role assignment, since such clauses are often not independently evaluative.

### OUTPUT FORMAT

Return:

```
{"spans": [...]}
```

If no evaluative content exists, return:

```
{"spans": []}
```

### EXAMPLES

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
