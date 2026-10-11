"""Versioned machine-readable integration contract."""


def document(origin):
    ticket = {'type': 'object', 'required': ['subject', 'message'], 'properties': {'subject': {'type': 'string', 'minLength': 1, 'maxLength': 120}, 'message': {'type': 'string', 'minLength': 1, 'maxLength': 3000}, 'source': {'type': 'string', 'maxLength': 24}, 'source_id': {'type': 'string', 'maxLength': 256}, 'customer': {'type': 'string', 'maxLength': 100}, 'company': {'type': 'string', 'maxLength': 100}, 'channel': {'type': 'string', 'maxLength': 40}}}
    identity = {'name': 'Idempotency-Key', 'in': 'header', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}, 'description': 'Reuse this key only for an identical request. Pending/uncertain operations are not repeated.'}
    classify = {'type': 'object', 'required': ['message'], 'properties': {'subject': {'type': 'string', 'maxLength': 120}, 'message': {'type': 'string', 'minLength': 1, 'maxLength': 3000}, 'engine': {'type': 'string', 'enum': ['laya', 'jev'], 'default': 'laya'}}}
    responses = {str(status): {'description': description} for status, description in ((200, 'Structured JSON result'), (400, 'Invalid input'), (401, 'Missing/expired integration key'), (403, 'Insufficient scope'), (409, 'Conflicting or pending request'), (429, 'Rate limit or workspace capacity'), (502, 'Model/provider failure'), (503, 'Service/model unavailable'))}
    def post(summary, schema, extra=None):
        return {'post': {'summary': summary, 'parameters': [identity, *(extra or [])], 'requestBody': {'required': True, 'content': {'application/json': {'schema': schema}}}, 'responses': responses}}
    path_id = {'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}
    return {'openapi': '3.1.0', 'info': {'title': 'Laya × Jev Ticket API', 'version': '0.2.0', 'description': 'Workspace-scoped integration. Import and sync do not call AI. Jev classification explicitly sends the selected input to TypeSafe.'}, 'servers': [{'url': origin}], 'security': [{'bearerAuth': []}], 'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer'}}, 'schemas': {'TicketInput': ticket}}, 'paths': {
        '/v1/classify': post('Classify without storing the original ticket; requires classify', classify),
        '/v1/compare': post('Explicitly call Laya and Jev; requires classify', {**classify, 'properties': {k: v for k, v in classify['properties'].items() if k != 'engine'}}),
        '/v1/tickets': {**post('Import/upsert up to 100 tickets; requires tickets:write', {'type': 'object', 'required': ['tickets'], 'properties': {'tickets': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': ticket}, 'update': {'type': 'boolean', 'default': False}}}), 'get': {'summary': 'List workspace tickets; requires tickets:read', 'parameters': [{'name': 'offset', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 0, 'maximum': 1000}}, {'name': 'limit', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 100}}], 'responses': responses}},
        '/v1/tickets/{id}': {'get': {'summary': 'Read one workspace ticket; requires tickets:read', 'parameters': [path_id], 'responses': {**responses, '404': {'description': 'Ticket not found'}}}},
        '/v1/tickets/{id}/classify': post('Classify and save a ticket result; requires classify and tickets:write', {'type': 'object', 'required': ['expected_revision'], 'properties': {'engine': {'type': 'string', 'enum': ['laya', 'jev']}, 'expected_revision': {'type': 'integer', 'minimum': 0}}}, [path_id]),
        '/v1/requests/{id}': {'get': {'summary': 'Inspect request outcome; requires tickets:read', 'parameters': [path_id], 'responses': {**responses, '404': {'description': 'Request not found'}}}},
    }}
