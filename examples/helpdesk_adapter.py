"""Map classification into an existing helpdesk without storing ticket text."""
from ticket_engine import LayaEngine

QUEUES = {'refund': 'billing', 'technical': 'technical', 'sales': 'sales', 'account': 'accounts', 'other': 'general'}


def route_ticket(engine, subject, message):
    result = engine.classify(message, subject=subject)
    return {'queue': 'review' if result.needs_review else QUEUES[result.category],
            'priority': result.priority, 'classification': result.to_dict()}


if __name__ == '__main__':
    engine = LayaEngine(model_path='models/ticket-finetuned-v5')
    print(route_ticket(engine, 'Synthetic billing example', 'Please refund a duplicate charge.'))
