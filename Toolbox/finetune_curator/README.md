# Toolbox/finetune_curator

Reviews conversation logs and tags high-authenticity exchanges
as fine-tuning training data candidates.

## Calling This Tool

    action: finetune_curator
    params: operation=curate_recent, days_back=7

    action: finetune_curator
    params: operation=export_dataset, min_quality=high, export_format=jsonl

    action: finetune_curator
    params: operation=status

## Scoring

Each exchange scored on three dimensions (0-10 each):
- Authenticity — does this sound like Hayeong?
- Quality — is the response genuinely good?
- Representativeness — is this worth having in training data?

Tiers: high (24+), medium (18-23), review (<18)

## Output

Curated examples saved to Toolbox/finetune_curator/curated/
Exported datasets saved to Logs/finetune_datasets/