"""Fail automatic applies that delete or replace existing resources."""
import json
import sys


def inspect(plan):
    changes = plan.get('resource_changes', [])
    destructive = [item['address'] for item in changes
                   if 'delete' in item['change']['actions']]
    if destructive:
        raise ValueError('Plano inclui exclusao/substituicao: ' + ', '.join(destructive))
    counts = {action: sum(action in item['change']['actions'] for item in changes)
              for action in ('create', 'update', 'no-op')}
    return counts


if __name__ == '__main__':
    with open(sys.argv[1], encoding='utf-8-sig') as stream:
        print(json.dumps(inspect(json.load(stream))))
