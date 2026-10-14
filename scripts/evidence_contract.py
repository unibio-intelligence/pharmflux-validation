"""Bind readable evidence tables and reports to one recorded engine."""
import csv
import gzip
import json

REPORTS = ('omex-rxode2', 'mrgsolve', 'ordinarydiffeq', 'roadrunner', 'copasi',
           'amici', 'source-presets', 'nlmixr2-conditions-bdf',
           'nlmixr2-conditions-rodas5p', 'nlmixr2-conditions-patched-rxode2-bdf',
           'nlmixr2-conditions-patched-rxode2-rodas5p', 'individual-fitting')


def max_error(comparison):
    if 'max_scaled_error' in comparison:
        return comparison['max_scaled_error']
    columns = comparison.get('columns', [])
    return max((x['max_scaled_error'] for x in columns), default='')


def simulation_rows(reports):
    rows = []
    def add(suite, model, case, solver, status, comparison):
        rows.append(dict(suite=suite, model=model, case=case, solver=solver,
                         status=status, max_scaled_error=max_error(comparison)))
    for model in reports['omex-rxode2']['models']:
        for case in model['cases']:
            for solver in case['solvers']:
                add('omex-rxode2', model['model_id'], case['scenario_id'],
                    solver['solver'], solver['status'], solver['comparison'])
    for name in REPORTS[1:6]:
        for case in reports[name]['cases']:
            for solver, comparison in case['comparisons'].items():
                add(name, case['model_id'], case['scenario_id'], solver,
                    comparison['status'], comparison)
    for case in reports['source-presets']['cases']:
        add('source-presets', case['model_id'], case['scenario_id'],
            'diffsol_bdf', case['status'], case)
    for name in REPORTS[7:11]:
        for model in reports[name]['models']:
            for case in model['cases']:
                solver = 'diffsol_rodas5p' if name.endswith('rodas5p') else 'diffsol_bdf'
                add(name, model['model_id'], case['condition_id'], solver,
                    case['status'], case)
    return rows


def fitting_rows(reports):
    fields = ('dataset', 'subject', 'solver', 'status', 'native_convergence',
              'reference_convergence', 'nll_difference',
              'prediction_max_absolute_difference', 'max_parameter_relative_difference')
    return [{key: (max(p['relative_difference'] for p in row['parameters'].values())
                   if key == 'max_parameter_relative_difference' else row[key])
             for key in fields} for row in reports['individual-fitting']['rows']]


def verify_evidence(root):
    env = json.loads((root / 'environment.json').read_text())
    summary = json.loads((root / 'results/summary.json').read_text())
    if summary['engine'] != env['engine'] or summary['cli_sha256'] != env['cli_sha256']:
        raise ValueError('summary and environment identities differ')
    expected = env['engine']['compiler_source_sha256']
    def check_identity(value):
        if isinstance(value, dict):
            if 'compiler_source_sha256' in value and value['compiler_source_sha256'] != expected:
                raise ValueError('report compiler source differs from environment')
            for child in value.values():
                check_identity(child)
        elif isinstance(value, list):
            for child in value:
                check_identity(child)
    reports = {}
    for name in REPORTS:
        reports[name] = json.loads(gzip.decompress((root / 'results' / (name + '.json.gz')).read_bytes()))
        report = reports[name]
        if report.get('compiler_source_sha256') != expected or report.get('cli_sha256') != env['cli_sha256']:
            raise ValueError('report build identity differs: ' + name)
        check_identity(report)
    for name, rows in [('simulations.csv', simulation_rows(reports)),
                       ('fitting.csv', fitting_rows(reports))]:
        with (root / 'results' / name).open(newline='') as stream:
            actual = list(csv.DictReader(stream))
        expected_rows = [{key: str(value) for key, value in row.items()} for row in rows]
        if actual != expected_rows:
            raise ValueError('CSV does not match numerical reports: ' + name)
