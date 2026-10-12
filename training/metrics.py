"""Small transparent metrics; no network or model dependencies."""
from collections import Counter


def classification(gold, predicted, labels):
    if len(gold) != len(predicted) or not gold:
        raise ValueError('Non-empty paired predictions required.')
    matrix = {str(label): {str(other): 0 for other in labels} for label in labels}
    for expected, actual in zip(gold, predicted):
        matrix[str(expected)][str(actual)] += 1
    counts = Counter(gold)
    per_class = {}
    for label in labels:
        tp = sum(a == b == label for a, b in zip(gold, predicted))
        fp = sum(a != label and b == label for a, b in zip(gold, predicted))
        fn = sum(a == label and b != label for a, b in zip(gold, predicted))
        per_class[str(label)] = {'n': counts[label], 'precision': tp / (tp + fp) if tp + fp else 0,
                                 'recall': tp / (tp + fn) if tp + fn else 0,
                                 'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}
    present = [value['f1'] for value in per_class.values() if value['n']]
    return {'n': len(gold), 'accuracy': sum(a == b for a, b in zip(gold, predicted)) / len(gold),
            'macro_f1': sum(present) / len(present), 'per_class': per_class, 'confusion_matrix': matrix}


def recommendation(baseline, candidate):
    improvements = [candidate[field]['macro_f1'] - baseline[field]['macro_f1'] for field in baseline]
    regressions = any(candidate[field]['macro_f1'] < baseline[field]['macro_f1'] - .02 for field in baseline)
    class_regression = any(new['n'] and new['recall'] < baseline[field]['per_class'][label]['recall'] - .15
                           for field, values in candidate.items() for label, new in values['per_class'].items())
    return not regressions and not class_regression and sum(improvements) / len(improvements) > .001
