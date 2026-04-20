import pickle

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RANDOM_STATE = 42
TEST_SIZE = 0.2
TARGET_COLUMN = "target"
MODEL_OUTPUT_PATH = "model.pkl"
DISEASE_CLASS = 0
FEATURE_COLUMNS = [
    "age",
    "sex",
    "cp",
    "trestbps",
    "chol",
    "fbs",
    "restecg",
    "thalach",
    "exang",
    "oldpeak",
    "slope",
    "ca",
    "thal",
]


def load_dataset(path="heart.csv"):
    return pd.read_csv(path)


def get_imbalance_strategy(y):
    ratios = y.value_counts(normalize=True).sort_index() * 100
    imbalance_gap = abs(ratios.get(1, 0) - ratios.get(0, 0))
    if imbalance_gap > 10:
        return "class_weight='balanced' enabled because the dataset is imbalanced."
    return "class_weight='balanced' enabled for robustness even though the dataset is fairly balanced."


def print_target_distribution(y):
    counts = y.value_counts().sort_index()
    ratios = (y.value_counts(normalize=True).sort_index() * 100).round(2)

    print("Target distribution:")
    for target_value in counts.index:
        print(f"  Class {target_value}: {counts[target_value]} samples ({ratios[target_value]}%)")

    print(get_imbalance_strategy(y))


def get_feature_importance(model, feature_columns):
    classifier = model.named_steps["classifier"]

    if hasattr(classifier, "feature_importances_"):
        importances = classifier.feature_importances_
    elif hasattr(classifier, "coef_"):
        importances = abs(classifier.coef_[0])
    else:
        importances = [1 / len(feature_columns)] * len(feature_columns)

    total = sum(importances) or 1
    importance_dict = {
        feature: round(float(score / total), 6)
        for feature, score in zip(feature_columns, importances)
    }
    return dict(sorted(importance_dict.items(), key=lambda item: item[1], reverse=True))


def evaluate_model(model_name, model, X_train, X_test, y_train, y_test):
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    accuracy = accuracy_score(y_test, predictions)
    matrix = confusion_matrix(y_test, predictions)
    report = classification_report(y_test, predictions, digits=4, output_dict=True)
    unique_predictions = sorted(pd.Series(predictions).unique().tolist())
    macro_f1 = report["macro avg"]["f1-score"]

    print(f"\n{'=' * 60}")
    print(f"{model_name}")
    print(f"{'=' * 60}")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Macro F1: {macro_f1:.4f}")
    print("Confusion Matrix:")
    print(matrix)
    print("Classification Report:")
    print(classification_report(y_test, predictions, digits=4))
    print(f"Predicted classes on test set: {unique_predictions}")

    return {
        "name": model_name,
        "model": model,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "confusion_matrix": matrix.tolist(),
        "classification_report": report,
        "predicted_classes": unique_predictions,
        "feature_importance": get_feature_importance(model, X_train.columns),
    }


def build_candidate_models():
    logistic_pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    max_iter=5000,
                    solver="liblinear",
                    C=1.0,
                    class_weight="balanced",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )

    random_forest_pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=400,
                    max_depth=10,
                    min_samples_split=4,
                    min_samples_leaf=2,
                    class_weight="balanced",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )

    return {
        "Logistic Regression": logistic_pipeline,
        "Random Forest": random_forest_pipeline,
    }


def build_model_bundle(df, y, best_result):
    class_profiles = (
        df.groupby(TARGET_COLUMN)[FEATURE_COLUMNS]
        .mean()
        .round(4)
        .to_dict(orient="index")
    )

    dataset_summary = {
        "rows": int(df.shape[0]),
        "features": int(len(FEATURE_COLUMNS)),
        "class_distribution": {int(key): int(value) for key, value in y.value_counts().sort_index().items()},
        "imbalance_strategy": get_imbalance_strategy(y),
    }

    metrics = {
        "accuracy": round(float(best_result["accuracy"]), 4),
        "macro_f1": round(float(best_result["macro_f1"]), 4),
        "confusion_matrix": best_result["confusion_matrix"],
        "classification_report": best_result["classification_report"],
    }

    return {
        "model": best_result["model"],
        "model_name": best_result["name"],
        "feature_columns": FEATURE_COLUMNS,
        "disease_class": DISEASE_CLASS,
        "healthy_class": 1,
        "metrics": metrics,
        "feature_importance": best_result["feature_importance"],
        "class_profiles": class_profiles,
        "dataset_summary": dataset_summary,
        "preprocessing": [
            "Stratified train-test split",
            "StandardScaler",
            "class_weight='balanced'",
        ],
    }


def main():
    df = load_dataset()
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    print_target_distribution(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    print(f"\nTrain shape: {X_train.shape}, Test shape: {X_test.shape}")

    candidate_models = build_candidate_models()
    results = []

    for model_name, model in candidate_models.items():
        results.append(evaluate_model(model_name, model, X_train, X_test, y_train, y_test))

    valid_results = [result for result in results if result["predicted_classes"] == [0, 1]]
    if not valid_results:
        raise RuntimeError("No candidate model predicted both classes on the test set.")

    best_result = max(valid_results, key=lambda result: (result["macro_f1"], result["accuracy"]))
    model_bundle = build_model_bundle(df, y, best_result)

    with open(MODEL_OUTPUT_PATH, "wb") as file:
        pickle.dump(model_bundle, file)

    print(f"\nBest model selected: {best_result['name']}")
    print(f"Saved improved model bundle to {MODEL_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
