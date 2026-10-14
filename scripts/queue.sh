#!/bin/sh
# Runs after the main evaluation: few-shot curve, zero-shot VLM baseline on our vLLM, benchmark.
cd /workspace/goodpart
while pgrep -f "goodpart.eval.run" >/dev/null; do sleep 30; done
python3 -m goodpart.eval.fewshot > results/fewshot.log 2>&1
python3 -m goodpart.eval.zeroshot --mode vllm --workers 32 > results/zeroshot_vllm.log 2>&1
python3 scripts/benchmark.py --category pcb1 --compare-cpu > results/benchmark.log 2>&1
echo QUEUE_DONE >> results/queue.log
