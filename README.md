# Data discovery and profiling

Run from this directory with Python 3.11.

```sh
python -m pip install -r backend/requirements.txt
python -m scripts.run_pipeline
python -m pytest -q
```

The pipeline regenerates `data/synthetic.sqlite` and writes `schema.json`,
`relationships.json`, `profiles.json`, and `ground_truth.json` to the same
directory. Use `--output-dir` to change the destination. Ground truth is for
evaluation only. Graph edges represent declared foreign keys.

Counts and distinctness cover the full source. Lengths, numeric summaries,
and structural indicators use up to 500 non-null values per column, ordered
by primary key where available. Use `--sample-size` to change this limit.
Patterns mask letters and digits and preserve selected structural separators.
Numeric summaries report mean and population standard deviation for samples
with at least two distinct numeric values.
