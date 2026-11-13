# Run the pipeline on a Kaggle GPU notebook (headless)

> **Verified workflow (2026-11-13, see SPEC.md section 14).** A kernel started by `launch push` cannot read Kaggle Secrets
> (`ConnectionError` from the secrets service), so run from the notebook editor:
> 1. `launch push ...` once (or `kaggle datasets version`) to create/update the code and verses datasets.
> 2. Open the notebook editor, replace the code with the full `pipeline/kaggle_run/kernel.py`, set `RUN_ARGS` at its top
>    (e.g. `"--steps 11 --workers 2 --align-device cuda"`), attach both datasets and the two AWS secrets (toggle ON),
>    Session options: Internet ON, accelerator GPU T4 x2.
> 3. Save Version > Save & Run All. Check the log line `[kernel] run args from notebook constant RUN_ARGS`; if it is
>    missing, the editor ran stale code (`kaggle kernels pull` to see what is saved).
> 4. `launch status` / `launch output`, then `aws s3 ls`, `pipeline merge`, `pipeline verify`.
> The CLI steps below still describe dataset creation; the push's kernel step is not the way to run.


Kaggle: 2x T4, internet on, ~29 GB RAM, 12 h cap per run. The kernel stops itself after `--max-hours` (default 11)
and exits 0; just push again to continue (finished verses are skipped). Results go to S3.

## One-time
1. Kaggle account, phone verified (needed for GPU + internet). `pip install kaggle`, API token in `~/.kaggle/kaggle.json`.
2. Dedicated IAM user with only this policy; make an access key for it:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::sloka-poc-audio-785703562757"},
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"],
     "Resource": "arn:aws:s3:::sloka-poc-audio-785703562757/pipeline/*"},
    {"Effect": "Allow", "Action": "s3:GetObject",
     "Resource": "arn:aws:s3:::sloka-poc-audio-785703562757/setup/*"}
  ]
}
```

## Each run (on the device that holds the verses; repo checked out)
```
python pipeline/tools/epic_json_to_jsonl.py <root> ramayana.jsonl --work ramayana     # convert
python pipeline/tools/validate_input.py ramayana.jsonl                                # validate
python -m pipeline.kaggle_run.launch push --user <kaggle_user> --jsonl ramayana.jsonl --dry-run   # inspect staging
python -m pipeline.kaggle_run.launch push --user <kaggle_user> --jsonl ramayana.jsonl \
       --run-args "--chapters 1-10"                                                   # real push (validates again)
```
3. After the first push open the notebook (kaggle.com/code/<user>/sloka-pipeline) > Add-ons > Secrets: add
   `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (optional `AWS_DEFAULT_REGION`, default ap-south-1) and attach them.
   The CLI cannot set secrets. Check Session options: accelerator GPU T4 x2, internet on. Then push again (or
   Save Version > Save & Run All).
4. Watch: `python -m pipeline.kaggle_run.launch status --user <kaggle_user>`
5. Fetch log/status: `python -m pipeline.kaggle_run.launch output --user <kaggle_user> --out kaggle_out`
   (`status.json` has exit codes and the last 50 log lines; no secrets).
6. Merge on the local machine: `python -m pipeline merge --into <store> --from s3://sloka-poc-audio-785703562757/pipeline/ramayana/`

Uploaded to Kaggle: `pipeline/` and `backend/engine` code, `config.json`, your JSONL. Never uploaded: weights,
`EdgeSanskrit-TTS/`, `.env`, secret-like files. Weights are fetched inside the kernel from S3 `setup/`.
Datasets and notebook are private. Unverified: the `--accelerator` flag and exact machine-shape metadata of your CLI version.
