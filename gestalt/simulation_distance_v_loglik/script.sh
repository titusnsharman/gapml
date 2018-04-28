#!/bin/sh

cd /home/jfeng2/gestaltamania/gestalt/

OVERWRITE="0"

FILE="simulation_distance_v_loglik/_output/{OUTDIR}/distance_v_loglik_results.pkl"
echo $FILE
# Check if file exists already or overwrite is allowed
if [ ! -f "$FILE" ] || [ "$OVERWRITE" = "1" ]; then
    python simulate_distance_v_loglik.py \
        --model-seed {model_seed} \
        --data-seed {data_seed} \
        --time {time} \
	--min-leaves 5 \
	--max-leaves {max_leaves} \
        --variance-target-lam {variance} \
	--num-moves 20 \
	--num-searches 6 \
	--max-explore-trees 6 \
	--max-iters 2000 \
	--do-distribute \
        --out-folder simulation_distance_v_loglik/_output/{OUTDIR}
else
    echo "File exists already"
fi
