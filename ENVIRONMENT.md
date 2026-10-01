# Environment

The completed project was developed on Windows 11 using Python 3.11
in a Conda environment.

- `environment.yml` records the complete final Conda environment,
  including transitive dependencies and pip-installed packages.
- `environment-lock-win-64.txt` records the exact Conda package builds
  used in the final Windows environment.

## Compatibility Notes

Several dependency versions were adjusted during development to resolve
compatibility issues.

### OpenSSL

The OpenSSL version was changed several times during environment
configuration and was ultimately pinned to the version recorded in the
final environment files because other tested versions caused compatibility
problems.

### pandas / PyArrow

Package versions were also adjusted while resolving Parquet compatibility
issues. The versions recorded in the environment files correspond to the
final environment used to execute the completed notebooks.

## External Models

- Translation tokenizer: `Helsinki-NLP/opus-mt-roa-en`
- Translation model: `R4kSo1997/opus-mt-pt-en-onnx-int8`
- Sentence embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- LLM extraction model: Gemini 3.1 Flash-Lite