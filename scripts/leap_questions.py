#!/usr/bin/env python3
"""Dump a LEAP survey's rows from mart.mart_survey_question to a JSON snapshot.

Uses ADC (the data-warehouse venv's python, or any env with google-cloud-bigquery).

    scripts/leap_questions.py SURVEY_ID > questions.json
"""
import collections
import json
import sys

from google.cloud import bigquery

G = collections.OrderedDict  # question_group_id -> group dict


def main(survey_id):
    c = bigquery.Client()
    rows = [dict(r) for r in c.query(f"""
        select * except(survey_id, project_id, question_source_id, question_group_source_id,
                        question_resolution_status, scenario_id)
        from `data-warehouse-dev-492608.mart.mart_survey_question`
        where survey_id = '{survey_id}'""")]
    for r in rows:
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    groups: G = collections.OrderedDict()
    for r in rows:
        g = groups.get(r["question_group_id"])
        if g is None:
            g = groups[r["question_group_id"]] = {
                "question_group_id": r["question_group_id"],
                "question_type": r["question_type"],
                "question_group_text": r["question_group_text"],
                "background": r["question_group_background_info"],
                "resolution_criteria": r["question_group_resolution_criteria"],
                "unit": r["unit_display_text"], "unit_name": r["unit_name"],
                "unit_min_value": r["unit_min_value"], "unit_max_value": r["unit_max_value"],
                "scenario_name": r["scenario_name"], "scenario_description": r["scenario_description"],
                "survey_end_date": r["survey_end_date"],
                "questions": []}
        g["questions"].append({k: r[k] for k in ("question_id", "question_dimension",
                                                 "question_percentile", "question_resolution_date")})
    json.dump({"survey_id": survey_id,
               "survey_source_id": rows[0]["survey_source_id"],
               "groups": list(groups.values())}, sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
