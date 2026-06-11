Third-Party Notices
===================

This project includes software from the following third parties:

1. OpenSquilla Router
   - License: Apache License 2.0
   - Source: https://github.com/opensquilla/opensquilla
   - Commit: 5409a22a5205846a6f9998e2d361cf286d8caa8d
   - License file: third_party/licenses/OpenSquilla-Apache-2.0.txt
   - Usage: ML-based route classification (R0-R3) for complexity analysis

2. BAAI/bge-small-zh-v1.5
   - License: MIT License
   - Source: https://huggingface.co/BAAI/bge-small-zh-v1.5
   - License file: third_party/licenses/BAAI-bge-small-zh-v1.5-MIT.txt
   - Usage: BGE embedding model for semantic feature extraction (1536-dim)

Notes:
- The OpenSquilla runtime bundle (model files, features, runtime_src) is NOT
  distributed with this project. It must be obtained separately and referenced
  via the AIROUTER_OPENSQUILLA_BUNDLE_DIR environment variable.
- ML dependencies (lightgbm, onnxruntime, numpy, joblib, scikit-learn, tokenizers)
  are optional extras: pip install airouter[ml]
