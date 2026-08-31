# Image generation and vision critique — the fixed constraint block

This file is the reference for the illustration stage's fixed prompt template and the
vision critic. Consistency is the harness's job, not the image model's — the image
model has no memory across requests — so the same constraints are applied on every
render.

## Reference sheets (generated once, then locked)

One sheet per major character, generated up front from the canon appearance: a
model-sheet layout showing the full body plus a face close-up, every costume variant,
and the fixed colour palette, on a neutral background. Once a sheet passes vision
critique it is frozen and reused for the entire series.

## Scene illustrations (every chapter)

Every scene render:

- supplies the relevant locked character reference sheets as reference inputs, so the
  face, hair, costume, and palette recur exactly;
- uses one fixed style block — identical art style, lighting convention, and palette
  discipline — across the whole book;
- states the scene from the chapter's beats, and names which characters appear so the
  right sheets are attached.

## Vision critique (every image, bounded regeneration)

The vision critic compares each render against its target (the reference sheet for a
sheet render; the scene description plus the sheets for a scene render) and returns a
strict JSON verdict `{"passed": bool, "issues": [str, ...]}`. It rejects on: wrong
character, wrong costume, palette drift, anatomical errors, or extra/missing
characters. A rejected image is regenerated up to the configured cap; past that, the
image is parked (the image fails, not the book).
