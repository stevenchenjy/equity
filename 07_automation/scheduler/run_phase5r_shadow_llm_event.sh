#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
runner="${project_root}/09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py"
evaluator="${project_root}/09_scripts/phase5r/evaluate_phase5r_shadow_llm_incremental_value.py"
packet="${project_root}/03_source_data/phase5r/phase5r_llm_evidence_packet.json"
runs_root="${project_root}/08_reviews/phase5r_shadow_llm/runs.local"
evaluation_output="${project_root}/08_reviews/phase5r_shadow_llm/reviews.local/evaluation.json"

[[ -x "${python_bin}" ]]
[[ -f "${runner}" ]]
[[ -f "${evaluator}" ]]
[[ -f "${packet}" ]]

runner_status=0
"${python_bin}" "${runner}" --auto-live --packet "${packet}" || runner_status=$?

evaluator_status=0
"${python_bin}" "${evaluator}" \
    --runs-root "${runs_root}" \
    --official-evidence-packet "${packet}" \
    --output "${evaluation_output}" || evaluator_status=$?

if (( runner_status != 0 )); then
    /usr/bin/printf '%s\n' "shadow_eval_event=failed runner_exit=${runner_status} evaluator_exit=${evaluator_status}"
    exit "${runner_status}"
fi
if (( evaluator_status != 0 )); then
    /usr/bin/printf '%s\n' "shadow_eval_event=failed runner_exit=0 evaluator_exit=${evaluator_status}"
    exit "${evaluator_status}"
fi

/usr/bin/printf '%s\n' "shadow_eval_event=complete canonical_effect=false email_eligible=false"
