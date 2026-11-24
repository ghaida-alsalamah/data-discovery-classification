"""Benchmark the released standalone OpenMetadata PII classifier.

This optional local-only path imports the separately licensed upstream distribution.
It never starts a catalog server, syncs tags, or auto-downloads NLP assets.
"""
import importlib.util

# Coarse pattern results such as an ordinary date, location or national origin
# do not by themselves establish direct PII. Preserve all returned native labels.
DIRECT_TAGS = {
    "person", "email", "email_address", "phone_number", "phone", "iban", "iban_code",
    "credit_card", "us_ssn", "us_bank_number", "us_driver_license", "us_passport",
    "government_id", "passport", "passport_number", "bank_account_number",
    "in_aadhaar", "uk_nhs", "au_tfn", "sg_nric_fin", "driver_license",
}


class OpenMetadataPII:
    def __init__(self):
        from metadata.pii.algorithms.classifiers import HeuristicPIIClassifier
        from metadata.pii.model_registry import get_model_for_language
        from metadata.generated.schema.type.classificationLanguages import ClassificationLanguage

        model = get_model_for_language(ClassificationLanguage.en)
        if not importlib.util.find_spec(model):
            raise RuntimeError(f"Preinstall OpenMetadata's {model} before reading source samples.")
        self.classifier = HeuristicPIIClassifier()

    def classify(self, values, column):
        from metadata.generated.schema.entity.data.table import DataType

        raw_type = column["type"].upper().split("(", 1)[0]
        sql_type = getattr(DataType, raw_type, None)
        result = self.classifier.predict_scores(values, column_name=column["name"], column_data_type=sql_type)
        scores = {str(key.value): float(score) for key, score in result.items()}
        # Apply the 80% confidence comparison separately from unfiltered native scores.
        return {"native_scores": scores,
                "native_tags": sorted(label for label, score in scores.items()
                                      if label.lower() in DIRECT_TAGS and score >= .80)}
