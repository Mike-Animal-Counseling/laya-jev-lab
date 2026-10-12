"""Create synthetic, private fixtures for trying intake, API and training previews."""
import argparse
import csv
from email.message import EmailMessage
from email.policy import SMTP
import json
from pathlib import Path


EXAMPLES = {
    'refund': ('Duplicate payment', 'Our subscription was charged twice. Please refund the extra payment.'),
    'technical': ('Export failure', 'The report export fails with an error. Please help fix the export.'),
    'sales': ('Team pricing', 'We would like to compare the team plan prices before purchasing.'),
    'account': ('Login access', 'I cannot sign in to my account. Please help reset my login access.'),
    'other': ('Product feedback', 'I suggest adding a compact view to the dashboard. Thank you for considering it.'),
}


def write_csv(path, headers, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('var/demo-data'))
    args = parser.parse_args()
    directory = args.output
    filenames = ('tickets.csv', 'training.csv', 'demo-email.eml', 'api-tickets.json')
    if any((directory / name).exists() for name in filenames):
        parser.error('Example files already exist. Choose a new output directory.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    tickets = [
        {'Subject': subject, 'Message': message, 'Customer': 'Demo customer',
         'Company': 'Demo company', 'Channel': 'Demo'}
        for subject, message in EXAMPLES.values()
    ]
    write_csv(directory / 'tickets.csv', ('Subject', 'Message', 'Customer', 'Company', 'Channel'), tickets)
    training = [
        {'subject': f'{subject} - example {number}',
         'message': f'{message} This is synthetic case {number} for workflow testing.',
         'category': category, 'group_id': f'demo-{category}-{number}'}
        for category, (subject, message) in EXAMPLES.items()
        for number in range(1, 11)
    ]
    write_csv(directory / 'training.csv', ('subject', 'message', 'category', 'group_id'), training)

    email = EmailMessage()
    email['From'] = 'Demo sender <demo@example.com>'
    email['To'] = 'Support <support@example.com>'
    email['Subject'] = 'Synthetic email import'
    email['Message-ID'] = '<demo-email@example.com>'
    email.set_content('This is a synthetic email. Please explain how to export a monthly report.')
    with (directory / 'demo-email.eml').open('xb') as stream:
        stream.write(email.as_bytes(policy=SMTP))
    payload = {'tickets': [
        {'subject': ticket['Subject'], 'message': ticket['Message'],
         'source': 'api', 'source_id': f'demo-api-{number}'}
        for number, ticket in enumerate(tickets, 1)
    ], 'update': True}
    with (directory / 'api-tickets.json').open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    for name in filenames:
        print(f'Created {name}')
    print('All examples are synthetic. Training data tests the workflow, not model quality.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
