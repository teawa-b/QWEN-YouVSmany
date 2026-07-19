# Episode samples

The old 90-second sample was removed when the product moved to its 30-second
AI Showrunner format. Generate a current deterministic sample with:

```powershell
python -m youvsmany.cli --topic "Pineapple belongs on pizza" --duration 30 `
  --challengers 2 --tags texture tradition --seed 0 --json
```

Current samples must validate as 6–7 turns, three total voices, and no more
than 30 seconds.
