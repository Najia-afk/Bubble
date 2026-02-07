"""Notebook execution endpoints."""

from flask import Blueprint, request, jsonify, g

notebook_bp = Blueprint('notebooks', __name__)


@notebook_bp.route("/notebooks", methods=['GET'])
def list_notebooks():
    """List available analysis notebooks."""
    from api.services.notebook_runner import get_notebook_runner

    try:
        runner = get_notebook_runner()
        notebooks = runner.list_available_notebooks()
        return jsonify({"notebooks": notebooks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@notebook_bp.route("/notebooks/execute", methods=['POST'])
def execute_notebook():
    """Execute an analysis notebook."""
    from api.services.notebook_runner import get_notebook_runner
    from api.tasks.monitor_tasks import run_notebook_task

    data = request.get_json() or {}
    notebook_name = data.get('notebook')
    parameters = data.get('parameters', {})
    async_exec = data.get('async', True)

    if not notebook_name:
        return jsonify({"error": "Missing 'notebook' parameter"}), 400

    try:
        if async_exec:
            task = run_notebook_task.delay(notebook_name, parameters)
            return jsonify({"status": "queued", "task_id": task.id, "notebook": notebook_name}), 202
        else:
            runner = get_notebook_runner()
            execution = runner.execute_notebook(notebook_name, parameters)
            return jsonify(execution.to_dict()), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@notebook_bp.route("/notebooks/executions", methods=['GET'])
def list_executions():
    """List notebook execution history."""
    from api.services.notebook_runner import get_notebook_runner

    limit = int(request.args.get('limit', 50))

    try:
        runner = get_notebook_runner()
        executions = runner.get_all_executions(limit=limit)
        return jsonify({"executions": [e.to_dict() for e in executions], "total": len(executions)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@notebook_bp.route("/notebooks/executions/<job_id>", methods=['GET'])
def get_execution(job_id):
    """Get execution status by job ID."""
    from api.services.notebook_runner import get_notebook_runner

    try:
        runner = get_notebook_runner()
        execution = runner.get_execution(job_id)

        if not execution:
            return jsonify({"error": f"Execution {job_id} not found"}), 404
        return jsonify(execution.to_dict()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@notebook_bp.route("/notebooks/analyze", methods=['POST'])
def run_analysis():
    """Run a pre-defined analysis on addresses."""
    from api.services.notebook_runner import get_notebook_runner

    data = request.get_json() or {}
    analysis_type = data.get('analysis_type')
    addresses = data.get('addresses', [])
    chain = data.get('chain', 'ETH')
    case_id = data.get('case_id')

    if not analysis_type:
        return jsonify({"error": "Missing 'analysis_type' parameter"}), 400
    if not addresses:
        return jsonify({"error": "Missing 'addresses' parameter"}), 400

    try:
        runner = get_notebook_runner()
        execution = runner.execute_analysis(
            analysis_type=analysis_type,
            addresses=addresses,
            chain=chain,
            case_id=case_id,
            **{k: v for k, v in data.items() if k not in ['analysis_type', 'addresses', 'chain', 'case_id']}
        )
        return jsonify(execution.to_dict()), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500
