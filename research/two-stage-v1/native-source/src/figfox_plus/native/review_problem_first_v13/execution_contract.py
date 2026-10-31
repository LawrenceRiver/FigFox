"""Generic executable protocol examples, tested against the actual local resolver.

Contains no figure-specific observations, target coordinates or acceptance data.
"""


def build_execution_contract(capabilities=None):
    from ..capabilities import normalize_capabilities
    policy=normalize_capabilities(capabilities)
    result = {
        'generated_python': {
            'INPUT_SVG': 'str: filesystem path to the current input SVG file, not XML source text',
            'OUTPUT_SVG': 'str: filesystem path where the resulting complete SVG must be written',
            'CURRENT_TP': 'dict: current-object measurement snapshot before this program; unchanged after your edits',
            'read_file': 'tree = xml.etree.ElementTree.parse(INPUT_SVG)',
            'read_source_string': 'ET.fromstring(xml_source_text) accepts XML markup only; never pass INPUT_SVG here',
            'runnable_example': (
                'import xml.etree.ElementTree as ET\n'
                'tree = ET.parse(INPUT_SVG)\n'
                'root = tree.getroot()\n'
                '# Apply the planned edits to declared targets here.\n'
                '# Keep target IDs and all structure outside the permitted scope.\n'
                'tree.write(OUTPUT_SVG, encoding="unicode")\n'
            ),
            'example_meaning': 'This parse/write example is executable but intentionally makes no repair. Replace the comment with your actual scoped edits; writing a file alone is not a completed repair.',
        },
        'expressions': {
            'calc_required': ['$calc', 'values'],
            'calc_schema': {'$calc': 'add|sub|mul|div|min|max', 'values': 'nonempty array of finite numbers or recursively resolved expressions'},
            'calc_shape': 'The operator is the string value of $calc; values is a sibling field in the same object, never nested inside $calc. args, operands, lhs/rhs and Python expression strings are not substitutes.',
            'arity': 'sub and div require exactly two values; add, mul, min and max require at least one. Booleans, NaN, infinity and division by zero are invalid.',
            'arithmetic_examples': [
                {'value': {'$calc':'add','values':[2,3]}, 'expected':5},
                {'value': {'$calc':'sub','values':[12,5]}, 'expected':7},
                {'value': {'$calc':'mul','values':[2,3]}, 'expected':6},
                {'value': {'$calc':'div','values':[12,3]}, 'expected':4},
                {'value': {'$calc':'min','values':[2,3]}, 'expected':2},
                {'value': {'$calc':'max','values':[2,3]}, 'expected':3},
            ],
            'measure_schema': {'$measure': {'ids':'nonempty list of actual current SVG IDs','edge':'left|top|right|bottom|width|height|cx|cy'}},
            'measure_meaning': 'Returns one numeric edge/size of the union of the selected objects, measured at execution time. The key is edge, not field. Reference and target below are placeholders; supply actual IDs.',
            'measured_difference_example': {'$calc':'sub','values':[
                {'$measure':{'ids':['reference'],'edge':'left'}},
                {'$measure':{'ids':['target'],'edge':'left'}},
            ]},
            'result_schema': {'$result': {'step':'previous operation result ID or explicitly depended-on program ID','path':'array of dictionary keys or numeric list indices'}},
            'example_result': {'$result':{'step':'previous_sample','path':['samples',0,'modal_hex']}},
            'execution_boundary': 'These are JSON data expressions resolved by native module operations. They are not Python syntax. In generated_python, compute ordinary Python numbers from the provided scene/snapshot instead.',
        },
    }

    if not policy['code_methods']:
        result['generated_python'].pop('CURRENT_TP')
        result.pop('expressions')
    return result
