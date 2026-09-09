#!/usr/bin/env bash
# setup_notebook_env.sh — prepare a PCAI notebook server for Lab 18.
#
# Installs RAPIDS (cuDF, cuML, cuVS) and the rest of the package set the lab
# notebook needs, IN THE ORDER THAT WORKS on the stock PCAI image:
#   1. upgrade the packages that pin numpy<2 (scikit-learn, scipy) and the rest
#   2. install RAPIDS 26.08 for CUDA 12 from NVIDIA's index (2-3 GB, 5-10 min)
#   3. force the numpy/pandas pair last (pip resolves them wrong otherwise)
#   4. verify in a FRESH python process (a running kernel reports stale versions)
#
# Run it from a Terminal in JupyterLab:
#     bash ~/pcai-dataeng-lab/setup_notebook_env.sh
# then restart the notebook kernel (Kernel > Restart Kernel) before running the lab.
#
# Safe to re-run: if the environment is already correct it does nothing.
set -u

want_ok() {
  python - <<'PY' 2>/dev/null
import importlib.metadata as md, importlib.util, sys
def v(m):
    try: return tuple(int(x) for x in md.version(m).split(".")[:2])
    except Exception: return None
ok = (v("numpy") and v("numpy")[0] >= 2
      and v("pandas") and v("pandas")[0] >= 3
      and v("scikit-learn") and v("scikit-learn") >= (1, 5)
      and v("scipy") and v("scipy") >= (1, 13)
      and v("mlflow") and v("mlflow")[0] == 2
      and all(importlib.util.find_spec(m) for m in ("cudf", "rmm", "cuml", "cuvs", "xgboost", "psycopg2")))
sys.exit(0 if ok else 1)
PY
}

echo "== Lab 18 notebook environment =="
if want_ok; then
  echo "environment already complete - nothing to install"
else
  echo "step 1/3  upgrading scikit-learn, scipy, xgboost, psycopg2, mlflow ..."
  pip install -q --upgrade "scikit-learn>=1.5" "scipy>=1.13" xgboost psycopg2-binary "mlflow>=2.9,<3" \
    || { echo "step 1 FAILED"; exit 1; }
  echo "step 2/3  installing RAPIDS 26.08 (cudf, rmm, cuml, cuvs) - 2-3 GB, be patient ..."
  pip install -q --extra-index-url https://pypi.nvidia.com \
    "cudf-cu12==26.8.*" "rmm-cu12==26.8.*" "cuml-cu12==26.8.*" "cuvs-cu12==26.8.*" \
    || { echo "step 2 FAILED"; exit 1; }
  echo "step 3/3  pinning numpy 2.x and pandas 3.0.x ..."
  pip install -q "numpy>=2,<3" "pandas>=3.0,<3.0.4" \
    || { echo "step 3 FAILED"; exit 1; }
  echo "(pip warnings about mlflow/pandas or torch CUDA libraries above are expected and harmless)"
fi

echo "== verify (fresh process) =="
python -c "import numpy,pandas,cudf,cuml,cuvs,sklearn,mlflow,xgboost; print('numpy',numpy.__version__,'| pandas',pandas.__version__,'| cudf',cudf.__version__,'| cuml',cuml.__version__,'| cuvs',cuvs.__version__,'| scikit-learn',sklearn.__version__,'| mlflow',mlflow.__version__)" \
  || { echo "VERIFY FAILED - see the import error above"; exit 1; }
echo
echo "environment ready. Now: Kernel > Restart Kernel in the notebook, then run it from the top."
