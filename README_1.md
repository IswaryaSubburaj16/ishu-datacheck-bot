# Ishu's DataCheck Bot (Prototype)

A chat window in Google Colab that checks a CSV table for possible data quality problems and answers questions about it.

## What it does
- Flags missing values, repeated rows or IDs, negative or unusual numbers, mixed spelling, invalid dates and some age problems
- Answers counts, percentages, averages, totals, top results and simple links between two number columns

## How it works
1. Simple questions and data checks are handled by Python rules.
2. For other questions, Google Gemini turns the question into a fixed plan.
3. Python checks the plan and does the calculation. No AI-written code is run.
4. AI-planned calculations show an "I understood" line so you can check the meaning.

For AI questions, Gemini receives the question, column names and column types. Data rows are not sent to it. Your CSV is loaded into your own Colab session, so use public or fake data only.

## Run it
1. In Google Colab choose **File > Open notebook > GitHub** and open `ishu_datacheck_bot.ipynb` from this repository.
2. Optional, for AI questions: add your own Gemini API key in Colab Secrets as `GEMINI_API_KEY` and allow notebook access.
3. Click **Run all** and scroll to the chat window.
4. Try `check all`, or press **CSV** to load your own file.

## Testing during development
- Practice data with planted errors: the check results matched the planted errors.
- Titanic data (891 rows): found 177 missing ages.
- Student performance data (1,000 rows), with real Gemini: average score by group, a percentage question, and a "why" question that was correctly declined. These two calculated results were not separately verified by hand.

## Limits
- It cannot explain causes, predict, give advice, draw charts or join files.
- The AI can misunderstand a question.
- Flagged values may be correct. It does not change your data.
- Some checks give false alarms, for example dates not written as YYYY-MM-DD. Some ID column names are not recognised.
- CSV files only, under 1 MB. It works only inside Google Colab.

Built by Iswarya Subburaj (Ishu), with AI assistance.
