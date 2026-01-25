"""
Notebook Runner Service - Execute Jupyter notebooks from backend

This service allows executing pre-defined analysis notebooks programmatically
for automated ML pipeline execution, batch analysis, and scheduled jobs.

Author: Bubble Platform Team
"""

import os
import json
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
import subprocess
import tempfile
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
from nbconvert import HTMLExporter


@dataclass
class NotebookExecution:
    """Represents a notebook execution job"""
    job_id: str
    notebook_path: str
    status: str = "pending"  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    output_path: Optional[str] = None
    html_report_path: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "notebook_path": self.notebook_path,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "parameters": self.parameters,
            "output_path": self.output_path,
            "html_report_path": self.html_report_path,
            "error_message": self.error_message,
            "execution_time_seconds": self.execution_time_seconds
        }


class NotebookRunnerService:
    """
    Service to execute Jupyter notebooks programmatically
    
    Features:
    - Execute notebooks with custom parameters
    - Generate HTML reports from executed notebooks
    - Track execution history and status
    - Support for async execution
    """
    
    # Available analysis notebooks
    AVAILABLE_NOTEBOOKS = {
        "wallet_classification": {
            "path": "notebooks/wallet_classification.ipynb",
            "description": "ML classification of wallet behavior patterns",
            "parameters": ["address", "chain", "case_id"]
        },
        "fund_tracing": {
            "path": "notebooks/fund_tracing_analysis.ipynb",
            "description": "Trace stolen funds through mixer and bridge hops",
            "parameters": ["source_address", "chain", "depth"]
        },
        "risk_scoring": {
            "path": "notebooks/risk_scoring.ipynb",
            "description": "Calculate comprehensive risk scores",
            "parameters": ["addresses", "chain"]
        },
        "network_analysis": {
            "path": "notebooks/network_graph_analysis.ipynb",
            "description": "Graph-based network analysis",
            "parameters": ["center_address", "chain", "hops"]
        },
        "temporal_patterns": {
            "path": "notebooks/temporal_pattern_analysis.ipynb",
            "description": "Time-series analysis of transaction patterns",
            "parameters": ["addresses", "chain", "start_date", "end_date"]
        },
        "feature_extraction": {
            "path": "notebooks/feature_extraction_pipeline.ipynb",
            "description": "Extract 50+ features for ML models",
            "parameters": ["addresses", "chain", "output_format"]
        }
    }
    
    def __init__(self, base_path: str = None, output_dir: str = None):
        """Initialize the notebook runner service"""
        self.base_path = base_path or os.getcwd()
        self.output_dir = output_dir or os.path.join(self.base_path, "reports", "notebooks")
        self.executions: Dict[str, NotebookExecution] = {}
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
    
    def list_available_notebooks(self) -> List[Dict[str, Any]]:
        """List all available analysis notebooks"""
        notebooks = []
        for name, info in self.AVAILABLE_NOTEBOOKS.items():
            notebook_path = os.path.join(self.base_path, info["path"])
            notebooks.append({
                "name": name,
                "path": info["path"],
                "description": info["description"],
                "parameters": info["parameters"],
                "exists": os.path.exists(notebook_path)
            })
        return notebooks
    
    def get_execution(self, job_id: str) -> Optional[NotebookExecution]:
        """Get execution status by job ID"""
        return self.executions.get(job_id)
    
    def get_all_executions(self, limit: int = 50) -> List[NotebookExecution]:
        """Get recent executions"""
        executions = list(self.executions.values())
        # Sort by started_at descending
        executions.sort(key=lambda x: x.started_at or datetime.min, reverse=True)
        return executions[:limit]
    
    def _inject_parameters(self, nb: nbformat.NotebookNode, parameters: Dict[str, Any]) -> nbformat.NotebookNode:
        """
        Inject parameters into notebook by adding a parameters cell at the top
        
        This follows the papermill convention of parameter injection
        """
        # Create parameter cell content
        param_lines = ["# Injected Parameters", "# Auto-generated by NotebookRunnerService", ""]
        for key, value in parameters.items():
            if isinstance(value, str):
                param_lines.append(f'{key} = "{value}"')
            elif isinstance(value, list):
                param_lines.append(f'{key} = {json.dumps(value)}')
            else:
                param_lines.append(f'{key} = {value}')
        
        param_cell = nbformat.v4.new_code_cell(source="\n".join(param_lines))
        param_cell.metadata["tags"] = ["injected-parameters"]
        
        # Insert parameter cell after first markdown cell or at position 0
        insert_pos = 0
        for i, cell in enumerate(nb.cells):
            if cell.cell_type == "markdown":
                insert_pos = i + 1
                break
        
        nb.cells.insert(insert_pos, param_cell)
        return nb
    
    def execute_notebook(
        self, 
        notebook_name: str, 
        parameters: Dict[str, Any] = None,
        timeout: int = 600,
        generate_html: bool = True
    ) -> NotebookExecution:
        """
        Execute a notebook synchronously
        
        Args:
            notebook_name: Name of notebook from AVAILABLE_NOTEBOOKS or full path
            parameters: Dictionary of parameters to inject
            timeout: Execution timeout in seconds
            generate_html: Whether to generate HTML report
            
        Returns:
            NotebookExecution with execution results
        """
        job_id = str(uuid.uuid4())[:8]
        parameters = parameters or {}
        
        # Resolve notebook path
        if notebook_name in self.AVAILABLE_NOTEBOOKS:
            notebook_path = os.path.join(self.base_path, self.AVAILABLE_NOTEBOOKS[notebook_name]["path"])
        else:
            notebook_path = notebook_name if os.path.isabs(notebook_name) else os.path.join(self.base_path, notebook_name)
        
        # Create execution record
        execution = NotebookExecution(
            job_id=job_id,
            notebook_path=notebook_path,
            parameters=parameters,
            status="running",
            started_at=datetime.now()
        )
        self.executions[job_id] = execution
        
        try:
            # Check notebook exists
            if not os.path.exists(notebook_path):
                raise FileNotFoundError(f"Notebook not found: {notebook_path}")
            
            # Read notebook
            with open(notebook_path, 'r', encoding='utf-8') as f:
                nb = nbformat.read(f, as_version=4)
            
            # Inject parameters
            if parameters:
                nb = self._inject_parameters(nb, parameters)
            
            # Create executor
            ep = ExecutePreprocessor(
                timeout=timeout,
                kernel_name='python3',
                allow_errors=False
            )
            
            # Execute
            ep.preprocess(nb, {'metadata': {'path': os.path.dirname(notebook_path)}})
            
            # Generate output paths
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{os.path.basename(notebook_path).replace('.ipynb', '')}_{job_id}_{timestamp}"
            
            # Save executed notebook
            output_path = os.path.join(self.output_dir, f"{output_filename}.ipynb")
            with open(output_path, 'w', encoding='utf-8') as f:
                nbformat.write(nb, f)
            
            execution.output_path = output_path
            
            # Generate HTML report
            if generate_html:
                html_exporter = HTMLExporter()
                html_exporter.exclude_input = False
                html_exporter.exclude_output_prompt = True
                
                (body, resources) = html_exporter.from_notebook_node(nb)
                
                html_path = os.path.join(self.output_dir, f"{output_filename}.html")
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(body)
                
                execution.html_report_path = html_path
            
            # Update execution status
            execution.status = "completed"
            execution.completed_at = datetime.now()
            execution.execution_time_seconds = (execution.completed_at - execution.started_at).total_seconds()
            
        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)
            execution.completed_at = datetime.now()
            if execution.started_at:
                execution.execution_time_seconds = (execution.completed_at - execution.started_at).total_seconds()
        
        return execution
    
    def execute_analysis(
        self,
        analysis_type: str,
        addresses: List[str],
        chain: str = "ETH",
        case_id: str = None,
        **kwargs
    ) -> NotebookExecution:
        """
        Execute a pre-defined analysis workflow
        
        This is a convenience method that maps analysis types to notebooks
        """
        notebook_mapping = {
            "classification": "wallet_classification",
            "tracing": "fund_tracing",
            "risk": "risk_scoring",
            "network": "network_analysis",
            "temporal": "temporal_patterns",
            "features": "feature_extraction"
        }
        
        notebook_name = notebook_mapping.get(analysis_type)
        if not notebook_name:
            raise ValueError(f"Unknown analysis type: {analysis_type}. Available: {list(notebook_mapping.keys())}")
        
        # Build parameters
        parameters = {
            "addresses": addresses if isinstance(addresses, list) else [addresses],
            "chain": chain,
            **kwargs
        }
        if case_id:
            parameters["case_id"] = case_id
        
        # Handle specific analysis parameters
        if analysis_type == "tracing" and len(addresses) > 0:
            parameters["source_address"] = addresses[0]
            parameters.setdefault("depth", 5)
        elif analysis_type == "network" and len(addresses) > 0:
            parameters["center_address"] = addresses[0]
            parameters.setdefault("hops", 3)
        
        return self.execute_notebook(notebook_name, parameters)
    
    def create_template_notebook(
        self,
        name: str,
        title: str,
        description: str,
        analysis_cells: List[Dict[str, str]]
    ) -> str:
        """
        Create a template notebook for custom analysis
        
        Args:
            name: Notebook filename
            title: Title for the notebook
            description: Description markdown
            analysis_cells: List of {"code": "...", "markdown": "..."} cells
            
        Returns:
            Path to created notebook
        """
        nb = nbformat.v4.new_notebook()
        
        # Add header
        nb.cells.append(nbformat.v4.new_markdown_cell(f"# {title}\n\n{description}"))
        
        # Add setup cell
        setup_code = """
# Standard imports
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta

# Bubble platform imports
import sys
sys.path.insert(0, '..')
from api.services.feature_engineer import WalletFeatureEngineer
from api.services.data_access import DataAccess
from utils.database import get_session_factory

# Initialize
Session = get_session_factory()
session = Session()
data = DataAccess(session)
feature_engineer = WalletFeatureEngineer()

print("✅ Notebook initialized")
"""
        nb.cells.append(nbformat.v4.new_code_cell(source=setup_code))
        
        # Add analysis cells
        for cell in analysis_cells:
            if cell.get("markdown"):
                nb.cells.append(nbformat.v4.new_markdown_cell(cell["markdown"]))
            if cell.get("code"):
                nb.cells.append(nbformat.v4.new_code_cell(source=cell["code"]))
        
        # Add conclusion cell
        nb.cells.append(nbformat.v4.new_markdown_cell("## Conclusions\n\n*Add your analysis conclusions here*"))
        
        # Save notebook
        notebook_path = os.path.join(self.base_path, "notebooks", f"{name}.ipynb")
        os.makedirs(os.path.dirname(notebook_path), exist_ok=True)
        
        with open(notebook_path, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        return notebook_path


# Singleton instance
_notebook_runner = None

def get_notebook_runner() -> NotebookRunnerService:
    """Get singleton notebook runner instance"""
    global _notebook_runner
    if _notebook_runner is None:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _notebook_runner = NotebookRunnerService(base_path=base_path)
    return _notebook_runner
