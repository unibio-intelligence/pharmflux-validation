"""Offline regression checks for numerical acceptance and replay identity."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from compare_nlmixr_omex_fits import compare as compare_fits
from trajectory_comparison import compare_columns, read_reference


class TrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.reference = {"time": [0., 1.], "state__x": [2., 2.], "output__cp": [3., 3.]}
        self.native = {"times": [0., 1.], "states": [{"name": "x", "values": [2., 2.]}],
                       "outputs": [{"name": "cp", "values": [3., 3.]}]}

    def compare(self, native):
        return compare_columns(self.reference, native, ["state__x", "output__cp"])

    def test_complete_agreement_and_real_mismatch(self):
        self.assertEqual(self.compare(self.native)["status"], "matched")
        self.native["outputs"][0]["values"][1] += .1
        self.assertEqual(self.compare(self.native)["status"], "mismatch")

    def test_missing_empty_duplicate_unknown_series_rejected(self):
        for mutation in (lambda n: n.update(states=[], outputs=[]),
                         lambda n: n.update(states=[]),
                         lambda n: n["outputs"].append(copy.deepcopy(n["outputs"][0])),
                         lambda n: n["outputs"][0].update(name="unknown")):
            n = copy.deepcopy(self.native)
            mutation(n)
            with self.subTest(native=n), self.assertRaises(ValueError):
                self.compare(n)

    def test_short_vectors_cannot_broadcast(self):
        for values in ([], [3.], [3., 3., 3.]):
            n = copy.deepcopy(self.native)
            n["outputs"][0]["values"] = values
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "length"):
                self.compare(n)

    def test_finite_values_and_exact_grid_required(self):
        for value in (float("nan"), float("inf"), False):
            n = copy.deepcopy(self.native)
            n["outputs"][0]["values"][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.compare(n)
        for times in ([], [0.], [0., 1.01], [0., float("nan")]):
            n = dict(self.native, times=times)
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.compare(n)

    def test_projection_aliases_still_require_complete_columns(self):
        n = {"times": [0., 1.], "outputs": [
            {"name": "library_state_0", "values": [2., 2.]},
            {"name": "source_output_0", "values": [3., 3.]}]}
        self.assertEqual(self.compare(n)["status"], "matched")
        n["outputs"][0]["name"] = "library_state_-1"
        with self.assertRaises(ValueError):
            self.compare(n)

    def test_explicit_projection_aliases_override_reference_order(self):
        aliases={"library_state_9":"state__x", "source_output_4":"output__cp"}
        n={"times":[0.,1.],"outputs":[{"name":"source_output_4","values":[3.,3.]},
            {"name":"library_state_9","values":[2.,2.]}]}
        self.assertEqual(compare_columns(self.reference,n,["output__cp","state__x"],aliases)["status"],"matched")
        n["outputs"][0]["name"]="source_output_0"
        with self.assertRaises(ValueError):compare_columns(self.reference,n,["output__cp","state__x"],aliases)

    def test_only_uncompared_reference_diagnostics_may_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"reference.csv"
            p.write_text("time,kin,Cc,kin\n0,1,2,3\n")
            self.assertEqual(read_reference(p,["time","Cc"]),{"time":[0.],"Cc":[2.]})
            with self.assertRaises(ValueError):read_reference(p,["time","kin"])

    def test_malformed_reference_headers_and_rows_rejected(self):
        for text in ("time,output__cp,output__cp\n0,3,3\n", "time,output__cp\n0,3,4\n", "time,output__cp\n0\n"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "reference.csv"
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    read_reference(path)


class FitIdentityTests(unittest.TestCase):
    def test_fresh_binary_identity_and_recorded_identity_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "sample" / "1"
            folder.mkdir(parents=True)
            plan = {"cases": [{"dataset": "sample", "subject": 1, "observations": 1}],
                    "comparison_limits": {}, "cli_sha256": "archived-binary", "datasets": ["sample"]}
            (root / "plan.json").write_text(json.dumps(plan))
            with contextlib.redirect_stdout(io.StringIO()):
                result = compare_fits(root, cli_sha256="fresh-binary")
            self.assertEqual(result["cli_sha256"], "fresh-binary")
            self.assertEqual(result["recorded_cli_sha256"], "archived-binary")
            self.assertEqual(json.loads((root / "comparison.json").read_text())["cli_sha256"], "fresh-binary")


class RequestContractTests(unittest.TestCase):
    def setUp(self):
        self.request = {"regimen": {"observations": [
            {"time": {"value": 0., "unit": "h"}, "side": "post"},
            {"time": {"value": 1., "unit": "h"}, "side": "pre"}]}}
        self.native = {"times": [0., 1.], "sides": ["post", "pre"], "time_unit": "h",
                       "outputs": [{"name": "cp", "unit": "1", "values": [0., 0.]}]}
        self.model = {"time_unit": "h", "outputs": [{"name": "cp", "unit": "1"}]}

    def test_requested_sides_units_and_inventory(self):
        from trajectory_comparison import validate_run
        validate_run(self.native, self.request, self.model)
        for field, value in (("sides", ["post", "post"]), ("time_unit", "s"),
                             ("times", [0., 2.])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run(dict(self.native, **{field: value}), self.request, self.model)
        for mutation in (lambda n: n["outputs"][0].update(unit="mg"),
                         lambda n: n["outputs"].append(copy.deepcopy(n["outputs"][0])),
                         lambda n: n["outputs"][0].update(name="extra"),
                         lambda n: n["outputs"][0].update(values=[0.]),
                         lambda n: n["outputs"][0].update(values=[False, 0.])):
            n=copy.deepcopy(self.native);mutation(n)
            with self.subTest(native=n), self.assertRaises(ValueError):
                validate_run(n, self.request, self.model)

    def test_condition_mapping_cannot_broadcast_or_ignore_extra_outputs(self):
        from trajectory_comparison import compare_mapped
        reference={"time": [0., 1.], "Cc": [0., 0.]}
        self.assertEqual(compare_mapped(reference,self.native,{"Cc":"cp"})["status"],"match")
        for values in ([0.], [], [0.,float("inf")], [False,0.]):
            n=copy.deepcopy(self.native);n["outputs"][0]["values"]=values
            with self.subTest(values=values), self.assertRaises(ValueError):
                compare_mapped(reference,n,{"Cc":"cp"})
        n=copy.deepcopy(self.native);n["outputs"].append({"name":"extra","unit":"1","values":[0.,0.]})
        with self.assertRaises(ValueError):compare_mapped(reference,n,{"Cc":"cp"})


class FittingContractTests(unittest.TestCase):
    def make_case(self, root):
        folder=root/"sample/1";folder.mkdir(parents=True)
        limits={"parameter_atol":1e-6,"parameter_rtol":.001,"nll_atol":1e-4,
                "prediction_atol":1e-6,"prediction_rtol":.001}
        case={"dataset":"sample","subject":1,"observations":2,"estimated":["cl"]}
        (root/"plan.json").write_text(json.dumps({"cases":[case],"comparison_limits":limits,
            "cli_sha256":"archived","datasets":["sample"]}))
        reference={"status":"executed","parameters":{"cl":2.},"nll":3.,
                   "predictions":[{"TIME":0.,"IPRED":5.},{"TIME":1.,"IPRED":4.}]}
        (folder/"nlmixr2-result.json").write_text(json.dumps(reference))
        run={"regimen":{"observations":[{"time":{"value":t,"unit":"h"},"side":s}
             for t,s in [(0.,"post"),(1.,"pre")]]}}
        for solver in ("diffsol_bdf","diffsol_rodas5p"):
            (folder/(solver+"-request.json")).write_text(json.dumps({"problem":{"request":{
                "bounds":[{"parameter":"cl","lower":{"value":.1,"unit":"1/h"},"upper":{"value":10.,"unit":"1/h"}}],
                "objective":{"simulation":{"run":run}}}}}))
            (folder/(solver+"-result.json")).write_text(json.dumps({"fit":{"status":"converged",
                "parameters":{"cl":{"value":2.,"unit":"1/h"}},"objective":{"negative_log_likelihood":3.}}}))
            (folder/(solver+"-prediction.json")).write_text(json.dumps({"times":[0.,1.],"sides":["post","pre"],
                "time_unit":"h","outputs":[{"name":"cp","unit":"1","values":[5.,4.]}]}))
        return folder

    def test_positive_and_shifted_missing_nonfinite_time_grids(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=self.make_case(root)
            with contextlib.redirect_stdout(io.StringIO()): result=compare_fits(root,cli_sha256="actual")
            self.assertEqual(result["counts"],{"matched_converged":2})
            self.assertEqual(result["cli_sha256"],"actual")
            p=folder/"diffsol_bdf-prediction.json";original=json.loads(p.read_text())
            for times in ([100.,101.], [], [0.], [0.,float("nan")], [False,1.]):
                p.write_text(json.dumps(dict(original,times=times)))
                with self.subTest(times=times), self.assertRaises(ValueError):compare_fits(root)

    def test_empty_parameters_extra_outputs_and_wrong_counts_fail(self):
        for mode in ("empty_parameters","duplicate_output","extra_output","wrong_count","boolean_parameter","wrong_unit"):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);folder=self.make_case(root)
                if mode in ("empty_parameters","boolean_parameter"):
                    p=folder/"nlmixr2-result.json";j=json.loads(p.read_text());j["parameters"]={} if mode=="empty_parameters" else {"cl":True}
                elif mode=="wrong_count":
                    p=root/"plan.json";j=json.loads(p.read_text());j["cases"][0]["observations"]=1
                else:
                    p=folder/"diffsol_bdf-prediction.json";j=json.loads(p.read_text())
                    if mode=="wrong_unit":j["outputs"][0]["unit"]="mg"
                    else:j["outputs"].append(dict(j["outputs"][0],name="cp" if mode=="duplicate_output" else "extra"))
                p.write_text(json.dumps(j))
                with self.subTest(mode=mode), self.assertRaises(ValueError):compare_fits(root)


class ArchivedConditionWrapperTests(unittest.TestCase):
    def test_all_four_lanes_use_pinned_requests_and_reject_short_results(self):
        import os
        import subprocess
        import sys
        base=Path(os.environ.get("QSPQUEST_VALIDATION_ROOT", Path(__file__).resolve().parents[1])).resolve()
        self.assertTrue((base/"inputs").is_dir(),
                        "Missing validation inputs; set QSPQUEST_VALIDATION_ROOT to the complete validation checkout")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cli=root/"cli";rscript=root/"rscript"
            cli.write_text("#!"+sys.executable+"\n"+'''
import json,os,sys
m=json.load(open(sys.argv[2]));r=json.load(open(sys.argv[3]));obs=r["regimen"]["observations"]
assert m["schema"]=="qspquest.model/v0.1" and r["schema"]=="qspquest.run/v0.1"
n=len(obs);short=os.environ.get("VALIDATION_TEST_SHORT")=="1"
print(json.dumps({"times":[o["time"]["value"] for o in obs],"time_unit":m["time_unit"],
 "sides":[o["side"] for o in obs],"outputs":[{"name":o["name"],"unit":o["unit"],"values":[0.]*(1 if short else n)} for o in m["outputs"]]}))
''')
            rscript.write_text("#!"+sys.executable+"\n"+'''
import csv,json,sys
from pathlib import Path
if "validate_administered_history.R" in sys.argv[1]:sys.exit(0)
plan=json.load(open(sys.argv[2]));output=Path(sys.argv[3])
for case in plan["cases"]:
 request=json.load(open(case["qspquest_request"]))
 folder=output/case["condition_id"];folder.mkdir(parents=True)
 with (folder/"trajectory.csv").open("w") as f:
  writer=csv.writer(f);writer.writerow(["time","Cc","depot","central"])
  for obs in request["regimen"]["observations"]:writer.writerow([obs["time"]["value"],0.,0.,0.])
''')
            cli.chmod(0o755);rscript.chmod(0o755)
            for i,suite in enumerate(("nlmixr2-bdf","nlmixr2-rodas5p","nlmixr2-patched-bdf","nlmixr2-patched-rodas5p","nlmixr2-bdf")):
                out=root/str(i);env=dict(os.environ)
                if i==4:env["VALIDATION_TEST_SHORT"]="1"
                command=[sys.executable,"-B",str(base/"scripts/reproduce.py"),"--suite",suite,"--model","PK_1cmt",
                         "--case","no_dose","--cli",str(cli),"--rscript",str(rscript),"--output",str(out)]
                run=subprocess.run(command,capture_output=True,text=True,env=env)
                with self.subTest(suite=suite,short=i==4):
                    if i==4:
                        self.assertNotEqual(run.returncode,0)
                        self.assertIn("failed",(out/"results/summary.json").read_text())
                    else:
                        self.assertEqual(run.returncode,0,run.stderr)
                        self.assertEqual(json.loads((out/"summary.json").read_text())["counts"],{"match":1})




class ReplayFormatTests(unittest.TestCase):
    def test_declared_native_schemas_validate_without_mutating_inputs(self):
        from replay_formats import validate_native
        for kind in ("model", "run", "sensitivity", "fit"):
            original={"schema":f"qspquest.{kind}/v0.1", "parameters":{"cl":{"value":.3,"unit":"L/h"}}}
            if kind=="fit":
                original["problem"]={"request":{"objective":{"simulation":{
                    "schema":"qspquest.sensitivity/v0.1","run":{"schema":"qspquest.run/v0.1"}}}}}
            before=copy.deepcopy(original)
            self.assertEqual(validate_native(original,kind),before)
            self.assertEqual(original,before)

    def test_unknown_versions_kinds_and_nested_schemas_are_rejected(self):
        from replay_formats import validate_native
        for schema in (None,[],{},"qspquest.run/v0.2","qspquest.run/v2","another.run/v0.1","qspquest.fit/v0.1"):
            with self.subTest(schema=schema),self.assertRaises(ValueError):validate_native({"schema":schema},"run")
        with self.assertRaises(ValueError):validate_native({"schema":"qspquest.fit/v0.1","nested":{"schema":"another.run/v0.1"}},"fit")

    def test_condition_request_contract_verifies_exact_bytes(self):
        import hashlib
        from replay_formats import condition_request
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);payload=b'{"schema":"qspquest.run/v0.1"}'
            p=folder/"qspquest-request.json";p.write_bytes(payload)
            case={"qspquest_request_sha256":hashlib.sha256(payload).hexdigest()}
            self.assertEqual(condition_request(folder,case),p)
            for invalid in ({},{"other_request_sha256":case["qspquest_request_sha256"]},{"qspquest_request_sha256":"0"*64}):
                with self.assertRaises(ValueError):condition_request(folder,invalid)
            p.unlink()
            with self.assertRaises(ValueError):condition_request(folder,case)

    def test_scratch_copy_preserves_exact_input_bytes_and_hash(self):
        import hashlib
        from replay_formats import write_native_copy
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"input.json";target=Path(directory)/"qspquest-request.json"
            original=b'{"schema":"qspquest.run/v0.1", "values":[1,2,3]}\n'
            source.write_bytes(original);record=write_native_copy(source,target,"run")
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(target.read_bytes(),original)
            self.assertEqual(record["recorded_sha256"],hashlib.sha256(original).hexdigest())
            self.assertEqual(record["executed_sha256"],record["recorded_sha256"])


if __name__ == "__main__":
    unittest.main()
