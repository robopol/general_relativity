import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import threading
import sympy as sp
import queue
import sys
import io
import time
import traceback # For detailed error traceback

class RedirectText:
    """Redirects stdout to a Tkinter Text widget in a thread-safe way."""
    def __init__(self, text_widget):
        self.output = text_widget
        self.queue = queue.Queue()
        self.updating = True
        # Use a reference to the update_worker method
        self.update_thread = threading.Thread(target=self.update_worker, daemon=True)
        self.update_thread.start()

    def write(self, string):
        # Put into queue only if the thread is still supposed to be running
        if self.updating:
            self.queue.put(string)

    def update_worker(self):
        while self.updating:
            try:
                # Block with a timeout to avoid busy-waiting
                item = self.queue.get(block=True, timeout=0.1)
                if item is None: # Sentinel value to stop the thread
                    break 
                # Schedule the update in the main Tkinter thread
                self.output.after(0, self.update_text, item)
                self.queue.task_done()
            except queue.Empty:
                # If the queue is empty, wait a bit and try again
                time.sleep(0.05) 
            except Exception as e:
                # Print errors to stderr to avoid cluttering the LaTeX output
                print(f"Error in RedirectText.update_worker: {e}", file=sys.stderr)
                time.sleep(0.1)

    def update_text(self, string):
        # This method runs in the main Tkinter thread
        try:
            # Check if the widget still exists
            if self.output.winfo_exists():
                self.output.config(state=tk.NORMAL)
                self.output.insert(tk.END, string)
                self.output.see(tk.END) # Auto-scroll
                self.output.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Error updating Text widget: {e}", file=sys.stderr)
    
    def flush(self):
        # Needed for file-like object compatibility
        pass

    def stop(self):
        # Set the flag to False
        if self.updating:
            self.updating = False
            # Put a sentinel value to unblock the queue.get()
            self.queue.put(None) 
            # Optionally wait for the thread to finish (usually not necessary for daemon)
            # self.update_thread.join(timeout=0.5)

class LatexOutputFormatter:
    """Class for formatting LaTeX output."""
    
    @staticmethod
    def format_matrix(matrix):
        """Creates a LaTeX string for a matrix."""
        if not isinstance(matrix, sp.Matrix):
            return sp.latex(matrix)
        # Use bmatrix for nicer display
        return sp.latex(matrix, mode='inline', mat_delim='', mat_str='bmatrix')
    
    @staticmethod
    def format_tensor_component(name, indices, expr):
        """Formats a tensor component with indices into LaTeX."""
        indices_str = "".join(str(idx) for idx in indices)
        name_str = name
        is_vector_or_scalar_or_divergence = False
        
        # Special formatting for G^μ_ν and ∇_ν G^μν
        if name == "G^": # Mixed Einstein Tensor
            if len(indices) == 2:
                 name_str = f"G^{{{indices[0]}}}_{{{indices[1]}}}"
            else: # Index error?
                 name_str = f"G^{{{indices_str}}}_?"
        elif name == "\\nabla_\\nu G^": # Covariant Divergence
            if len(indices) == 1:
                name_str = f"\\nabla_\\nu G^{{{indices[0]}}}{{\\nu}}"
                is_vector_or_scalar_or_divergence = True
            else: # Index error?
                name_str = f"\\nabla_\\nu G^{{{indices_str}}}?"
        elif len(indices) == 2: # Assume R_μν, G_μν
            name_str = f"{name}_{{{indices_str}}}"
        elif len(indices) == 1: # Assume a vector
            name_str = f"{name}_{{{indices_str}}}" 
            is_vector_or_scalar_or_divergence = True
        elif len(indices) == 0: # Scalar
             name_str = name
             is_vector_or_scalar_or_divergence = True
        else: # More indices?
             name_str = f"{name}_{{{indices_str}}}"

        header = f"{name_str} = "
        
        expr_latex = sp.latex(expr)
        
        # Add newline only for rank-2 tensors (matrices) for better readability
        # Keep vectors, scalars, and divergence on a single line.
        newline = " \\\\ \n" if not is_vector_or_scalar_or_divergence else " " 
        
        # Resulting LaTeX string
        return f"{header}{expr_latex}{newline}\n"

class EinsteinCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("General Relativity Tensor Calculator (LaTeX Output)")
        # Increase window size for the metric definition Text widget
        self.root.geometry("1200x800") 
        
        self.running = False
        self.calculation_thread = None
        self.progress_var = tk.DoubleVar(value=0)
        self.stdout_redirector = None # Initialize later
        
        # Setup fonts
        self.setup_fonts()
        
        self.create_widgets()
        
        # Set default metric (Kerr)
        self.set_kerr_metric_default()
        
        # Handle window closing properly
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def on_closing(self):
        print("Closing application...")
        if self.stdout_redirector:
            self.stdout_redirector.stop()
        # Stop calculation if running
        if self.running:
             self.stop_calculation(force=True)
        self.root.destroy()

    def setup_fonts(self):
        # Set monospace font for better display of LaTeX code and metric definition
        font_family = "Consolas" if "Consolas" in font.families() else "Courier"
        self.code_font = font.Font(family=font_family, size=10)
        
    def create_widgets(self):
        # --- Main Frame --- 
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1) # Input column
        main_frame.columnconfigure(1, weight=3) # Output column
        main_frame.rowconfigure(1, weight=1)    # Output row expands

        # --- Input Panel Frame (Left Side) --- 
        input_panel = ttk.Frame(main_frame, padding="5")
        input_panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        input_panel.rowconfigure(3, weight=1) # Metric definition row expands

        # --- Input Parameters --- 
        param_frame = ttk.LabelFrame(input_panel, text="Spacetime Definition", padding="10")
        param_frame.grid(row=0, column=0, sticky="new", pady=(0, 10))
        param_frame.columnconfigure(1, weight=1)

        # Coordinates
        ttk.Label(param_frame, text="Coordinates:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.coords_var = tk.StringVar(value="t, r, theta, phi")
        ttk.Entry(param_frame, textvariable=self.coords_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        
        # Symbols
        ttk.Label(param_frame, text="Symbols:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.symbols_var = tk.StringVar(value="M, a")
        ttk.Entry(param_frame, textvariable=self.symbols_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(param_frame, text="(e.g., M, a, k, ... comma-separated)").grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=0)

        # --- Metric Tensor Definition --- 
        metric_frame = ttk.LabelFrame(input_panel, text="Metric Tensor g (Python Code)", padding="10")
        metric_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        metric_frame.rowconfigure(0, weight=1)
        metric_frame.columnconfigure(0, weight=1)

        self.metric_text = scrolledtext.ScrolledText(metric_frame, wrap=tk.WORD, height=15, 
                                                    font=self.code_font)
        self.metric_text.grid(row=0, column=0, sticky="nsew")
        ttk.Label(metric_frame, text="Define Python list of lists. Use 'sp.' prefix for SymPy functions.").grid(row=1, column=0, sticky="w", pady=(5,0))
        ttk.Label(metric_frame, text="Assign the final list/Matrix to the variable `metric_matrix`.", foreground="blue").grid(row=2, column=0, sticky="w", pady=(2,0))

        # --- Controls (Buttons & Progress Bar) --- 
        control_frame = ttk.Frame(input_panel, padding="5")
        control_frame.grid(row=4, column=0, sticky="sew")

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=(10, 5), anchor="w")
        
        self.run_button = ttk.Button(button_frame, text="Run Calculation", command=self.run_calculation)
        self.run_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_calculation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.clear_button = ttk.Button(button_frame, text="Clear Output", command=self.clear_output)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        progress_frame = ttk.Frame(control_frame)
        progress_frame.pack(fill=tk.X, pady=5, anchor="w")
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, expand=True)
        
        self.status_label = ttk.Label(progress_frame, text="Ready")
        self.status_label.pack(anchor="w")

        # --- Output Panel Frame (Right Side) --- 
        output_panel = ttk.Frame(main_frame, padding="5")
        output_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        output_panel.rowconfigure(0, weight=1)
        output_panel.columnconfigure(0, weight=1)

        output_frame = ttk.LabelFrame(output_panel, text="Results (LaTeX Code)", padding="10")
        output_frame.grid(row=0, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, 
                                                  state=tk.DISABLED, font=self.code_font)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        ttk.Label(output_frame, text="Copy this code and paste it into a LaTeX editor/renderer.").grid(row=1, column=0, sticky="w", pady=(5,0))
                
        # Initialize stdout redirection AFTER creating the output_text widget
        self.stdout_redirector = RedirectText(self.output_text)
            
    def set_kerr_metric_default(self):
        """Sets the Kerr metric as the default text."""
        self.coords_var.set("t, r, theta, phi")
        self.symbols_var.set("M, a") # Back to M, a for Kerr
        
        kerr_metric_string = (
            "# Kerr metric in Boyer-Lindquist coordinates\n"
            "# Required symbols: M, a (defined above)\n"
            "rho2 = r**2 + a**2 * sp.cos(theta)**2\n"
            "Delta = r**2 - 2*M*r + a**2\n\n"
            "# The resulting list must be assigned to 'metric_matrix'\n"
            "metric_matrix = [\n"
            "  [-(1 - 2*M*r / rho2), 0, 0, - (2 * M * a * r * sp.sin(theta)**2) / rho2],\n"
            "  [0, rho2 / Delta, 0, 0],\n"
            "  [0, 0, rho2, 0],\n"
            "  [- (2 * M * a * r * sp.sin(theta)**2) / rho2, 0, 0, ( (r**2 + a**2)**2 - a**2 * Delta * sp.sin(theta)**2 ) * sp.sin(theta)**2 / rho2]\n"
            "]"
        )
        # Clear existing text before inserting
        self.metric_text.delete(1.0, tk.END)
        self.metric_text.insert(tk.END, kerr_metric_string)
        
    # Keep the function for the original metric in case needed later
    def set_original_tono_metric_default(self):
        """Sets the metric from the original tono.py as default text."""
        self.coords_var.set("t, r, theta, phi")
        self.symbols_var.set("k") # Symbol k as in original
        
        original_metric_string = (
            "# Metric from original tono.py\n"
            "# Required symbols: k (defined above)\n"
            "# Function omega(r) is defined directly here as sp.Function\n"
            "omega = sp.Function('omega')(r)\n"
            "omega_diff_r = sp.diff(omega, r)\n\n"
            "# The resulting list must be assigned to 'metric_matrix'\n"
            "metric_matrix = [\n"
            "    [\n"
            "        -sp.exp(-2 * k / r) + omega**2 * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2,\n"
            "        omega_diff_r * t * omega * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2,\n"
            "        0,\n"
            "        -omega * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2\n"
            "    ],\n"
            "    [\n"
            "        omega_diff_r * t * omega * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2,\n"
            "        -sp.exp(2 * k / r) * (1 + omega_diff_r**2 * t**2 * r**2 * sp.sin(theta)**2),\n"
            "        0,\n"
            "        -omega_diff_r * t * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2\n"
            "    ],\n"
            "    [0, 0, r**2 * sp.exp(2 * k / r), 0],\n"
            "    [\n"
            "        -omega * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2,\n"
            "        -omega_diff_r * t * r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2,\n"
            "        0,\n"
            "        r**2 * sp.exp(2 * k / r) * sp.sin(theta)**2\n"
            "    ]\n"
            "]"
        )
        # Clear existing text before inserting
        self.metric_text.delete(1.0, tk.END)
        self.metric_text.insert(tk.END, original_metric_string)

    def update_status(self, text, progress=None):
        # Always schedule GUI updates from the main thread via after()
        def update_gui():
            if self.status_label.winfo_exists():
                 self.status_label.config(text=text)
            if progress is not None and self.progress_bar.winfo_exists():
                self.progress_var.set(progress)
        # Use after(0) to schedule the update as soon as possible
        if self.root.winfo_exists():
            self.root.after(0, update_gui) 
    
    def clear_output(self):
        if self.output_text.winfo_exists():
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.config(state=tk.DISABLED)
        self.update_status("Output cleared", 0)
        
    def run_calculation(self):
        if self.running:
            messagebox.showwarning("Warning", "Calculation is already running.")
            return
            
        # --- Get and Validate Inputs --- 
        coords_str = self.coords_var.get().strip()
        symbols_str = self.symbols_var.get().strip()
        metric_def_str = self.metric_text.get(1.0, tk.END).strip()

        if not coords_str:
             messagebox.showerror("Input Error", "Please enter coordinate names (comma-separated).")
             return
        if not metric_def_str:
             messagebox.showerror("Input Error", "Please enter the metric tensor definition.")
             return

        # Clear previous output
        self.clear_output()
        
        # Update button states
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.DISABLED)
        
        # Start calculation in a separate thread
        self.running = True
        self.progress_var.set(0)
        self.update_status("Starting calculation...", 0)
        # Pass inputs as arguments to the thread
        self.calculation_thread = threading.Thread(target=self.perform_calculation, 
                                                 args=(coords_str, symbols_str, metric_def_str))
        self.calculation_thread.daemon = True
        self.calculation_thread.start()
        
        # Periodically check calculation status
        self.root.after(100, self.check_calculation_status)
        
    def check_calculation_status(self):
        # If the thread is still running and the GUI exists
        if self.running and self.calculation_thread and self.calculation_thread.is_alive():
             if self.root.winfo_exists(): # Check if the window still exists
                 self.root.after(100, self.check_calculation_status)
        else:
            # Thread finished (normally, with error, or stopped)
            # If the window still exists, update the GUI
            if self.root.winfo_exists():
                self.finish_calculation()
        
    def stop_calculation(self, force=False):
        if not self.running and not force:
            return
            
        if self.running:
             print("\n% Stop command received...\n") 
             self.running = False # Set flag to stop loops in calculation
             self.update_status("Stopping calculation...", self.progress_var.get())
        elif force and self.calculation_thread and self.calculation_thread.is_alive():
             # Forced stop during window closing, thread might not be 'running'
             self.running = False
             print("\n% Forcing calculation stop during window close...\n")

        # The thread should terminate itself after checking self.running
        # finish_calculation is called automatically via check_calculation_status
            
    def print_separator(self):
        """Prints a separator line for LaTeX output."""
        print("\n%-----------------------------------------------------%\n")
    
    def print_section_header(self, text):
        """Prints a section header as a LaTeX comment."""
        print(f"\n% ===== {text} ===== %\n")
    
    def pretty_print_tensor_latex(self, tensor, name, indices_list):
        """Prints a tensor as a series of LaTeX expressions."""
        for indices in indices_list:
            if not self.running: # Check before each component
                raise InterruptedError("Calculation stopped by user during output printing")
                
            if len(indices) == 2:
                i, j = indices
                print(f"% Calculating/Printing component {name} with indices ({i},{j})") 
                latex_expr = LatexOutputFormatter.format_tensor_component(name, [i, j], tensor[i, j])
                print(latex_expr)
            elif len(indices) == 1:
                 i = indices[0]
                 print(f"% Calculating/Printing component {name} with index ({i})") 
                 latex_expr = LatexOutputFormatter.format_tensor_component(name, [i], tensor[i])
                 print(latex_expr)
            elif len(indices) == 0: # Scalar
                print(f"% Printing scalar {name}")
                latex_expr = LatexOutputFormatter.format_tensor_component(name, [], tensor)
                print(latex_expr)

    # Calculation now receives inputs as arguments
    def perform_calculation(self, coords_str, symbols_str, metric_def_str):
        calculation_successful = False
        # Namespace for evaluating/executing metric definition
        # Limited builtins for security
        safe_globals = {'sp': sp, '__builtins__': {}} 
        local_namespace = {} # Will hold coords, symbols, and metric result
        coords = []
        g = None
        n = 0
        
        try:
            # Redirect stdout to our Text widget
            old_stdout = sys.stdout
            sys.stdout = self.stdout_redirector
            
            self.update_status("Processing inputs...", 1)
            
            # --- Process Coordinates --- 
            self.print_section_header("Input Processing: Coordinates")
            try:
                coord_names = [s.strip() for s in coords_str.split(',') if s.strip()]
                if not coord_names:
                    raise ValueError("No coordinate names provided.")
                coords_syms = sp.symbols(coord_names, real=True)
                coords = list(coords_syms) if isinstance(coords_syms, (tuple, list)) else [coords_syms]
                n = len(coords)
                if n == 0: raise ValueError("Number of coordinates must be > 0.")
                for name, sym in zip(coord_names, coords):
                    local_namespace[name] = sym # Add to namespace for metric definition
                print(f"% Coordinates ({n}D): {', '.join(coord_names)}")
            except Exception as e:
                raise ValueError(f"Error processing coordinates '{coords_str}': {e}")
            
            # --- Process Symbols --- 
            self.print_section_header("Input Processing: Symbols")
            try:
                if symbols_str:
                    symbol_names = [s.strip() for s in symbols_str.split(',') if s.strip()]
                    if symbol_names:
                        symbols_obj = sp.symbols(symbol_names, real=True, positive=True)
                        current_symbols = list(symbols_obj) if isinstance(symbols_obj, (tuple, list)) else [symbols_obj]
                        for name, sym in zip(symbol_names, current_symbols):
                            local_namespace[name] = sym # Add to namespace
                        print(f"% Defined symbols: {', '.join(symbol_names)}")
                    else:
                        print("% No additional symbols defined.")
                else:
                     print("% No additional symbols defined.")
            except Exception as e:
                 raise ValueError(f"Error processing symbols '{symbols_str}': {e}")

            # --- Process Metric Definition --- 
            self.update_status("Processing metric definition...", 5)
            self.print_section_header("Input Processing: Metric Tensor")
            print(f"% Attempting to process metric definition code...\n")
            try:
                # Remove comments for safer execution
                metric_code_lines = []
                for line in metric_def_str.splitlines():
                    stripped_line = line.split('#', 1)[0].strip()
                    if stripped_line:
                        metric_code_lines.append(stripped_line)
                metric_code = '\n'.join(metric_code_lines)
                
                # Execute the metric definition code
                # This defines variables (like rho2, Delta) and metric_matrix in local_namespace
                exec(metric_code, safe_globals, local_namespace)
                
                # Retrieve the resulting matrix from the namespace
                if 'metric_matrix' not in local_namespace:
                    raise NameError("Variable `metric_matrix` was not defined in the metric code.")
                
                metric_input = local_namespace['metric_matrix']
                 
                # Convert to SymPy Matrix if necessary
                if isinstance(metric_input, list):
                    g = sp.Matrix(metric_input)
                elif isinstance(metric_input, sp.Matrix):
                    g = metric_input
                else:
                    raise TypeError("Metric definition must result in a Python list of lists or a sympy.Matrix.")
                
                # Validate dimensions
                if g.shape != (n, n):
                     raise ValueError(f"Metric dimensions {g.shape} do not match number of coordinates ({n}).")
                     
                print("% Metric definition successfully processed.")
                
            except Exception as e:
                # Print detailed error including traceback from exec if possible
                error_msg = f"Error processing metric definition: {e}\n" \
                            f"Check syntax, variable names, and use of 'sp.'.\n" \
                            f"Provided definition:\n------\n{metric_def_str}\n------"
                exc_type, exc_value, exc_traceback = sys.exc_info()
                # Only include traceback if it's relevant (not just the ValueError we raised)
                if exc_traceback and exc_traceback.tb_next: 
                    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                    error_msg += "\n% Traceback (from exec):\n% " + "% ".join(tb_lines) 
                # Raise as SyntaxError to be caught nicely below
                raise SyntaxError(error_msg)
            
            # === Start Calculations ===
            if not self.running: raise InterruptedError("Calculation stopped before starting computations")
            
            self.print_section_header(f"Metric Tensor g (Input {n}x{n})")
            print(LatexOutputFormatter.format_matrix(g))
            self.print_separator()
            
            # --- Inverse Metric --- 
            self.update_status("Calculating inverse metric...", 20)
            self.print_section_header("Inverse Metric Tensor g^{\\mu\\nu}")
            print("% Calculating g^{\\mu\\nu} = g^{-1}...\n")
            g_inv = sp.simplify(g.inv())
            print(LatexOutputFormatter.format_matrix(g_inv))
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after inverse metric")

            # --- Christoffel Symbols --- 
            self.update_status("Calculating Christoffel symbols...", 30)
            self.print_section_header("Christoffel Symbols \\Gamma^{\\rho}_{\\mu\\nu}")
            print("% Calculating Christoffel symbols... (Using sp.cancel() for speed)\n")
            Gamma = [[[sp.sympify(0) for _ in range(n)] for _ in range(n)] for _ in range(n)]
            for rho in range(n):
                # Update status less frequently for faster execution
                if mu == 0 and nu == 0:
                     self.update_status(f"Calculating Christoffel symbols (ρ={rho+1}/{n})...", 30 + ((rho + 1) / n * 15))
                for mu in range(n):
                    for nu in range(n):
                        if not self.running: raise InterruptedError(f"Calculation stopped at \\Gamma^{{{rho}}}_{{{mu}}}{{{nu}}}")
                        # print(f"% Calculating \\Gamma^{{{rho}}}_{{{mu}}}{{{nu}}}...") # Too verbose usually
                        sum_val = sp.sympify(0)
                        for lam in range(n): # lambda index
                             term = g_inv[rho, lam] * (sp.diff(g[lam, mu], coords[nu]) +
                                                     sp.diff(g[lam, nu], coords[mu]) -
                                                     sp.diff(g[mu, nu], coords[lam]))
                             sum_val += term
                        # Use sp.cancel() instead of sp.simplify() for performance
                        Gamma[rho][mu][nu] = sp.cancel(sp.Rational(1, 2) * sum_val) 
                # progress = 30 + ((rho + 1) / n * 15) # Moved update inside loop
                # self.update_status(f"Calculating Christoffel symbols (ρ={rho+1}/{n})", progress)
            print("% Calculation of Christoffel symbols finished.")
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after Christoffel symbols")

            # --- Ricci Tensor --- 
            self.update_status("Calculating Ricci tensor...", 45)
            self.print_section_header("Ricci Tensor R_{\\mu\\nu}")
            print("% Calculating Ricci tensor (using standard formula)...\n")
            R = sp.Matrix.zeros(n, n)
            for mu in range(n):
                 # Update status less frequently
                if nu == 0:
                    self.update_status(f"Calculating Ricci tensor (μ={mu+1}/{n})...", 45 + ((mu + 1) / n * 15))
                for nu in range(n):
                    if not self.running: raise InterruptedError(f"Calculation stopped at R_{{{mu}}}{{{nu}}}")
                    # print(f"% Calculating R_{{{mu}}}{{{nu}}}...") # Too verbose
                    
                    # R_μν = ∂_ρ Γ^ρ_μν - ∂_ν Γ^ρ_μρ + Γ^ρ_μν Γ^σ_ρσ - Γ^σ_μρ Γ^ρ_νσ
                    term1 = sum(sp.diff(Gamma[rho][mu][nu], coords[rho]) for rho in range(n))
                    term2 = sum(sp.diff(Gamma[rho][mu][rho], coords[nu]) for rho in range(n))
                    term3 = sum(sum(Gamma[rho][mu][nu] * Gamma[sigma][rho][sigma] for sigma in range(n)) for rho in range(n))
                    term4 = sum(sum(Gamma[sigma][mu][rho] * Gamma[rho][nu][sigma] for rho in range(n)) for sigma in range(n))
                    
                    # Simplify each component
                    R[mu, nu] = sp.simplify(term1 - term2 + term3 - term4)
                # progress = 45 + ((mu + 1) / n * 15) # Moved update inside loop
                # self.update_status(f"Calculating Ricci tensor (μ={mu+1}/{n})", progress)
            print("% Ricci Tensor R_{\\mu\\nu}:")
            print(LatexOutputFormatter.format_matrix(R))
            print("% Calculation of Ricci tensor finished.")
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after Ricci tensor")

            # --- Ricci Scalar --- 
            self.update_status("Calculating Ricci scalar...", 60)
            self.print_section_header("Ricci Scalar R")
            print("% Calculating Ricci scalar R = g^{\\mu\\nu} R_{\\mu\\nu}...\n")
            R_scalar_expr = sp.sympify(0)
            for i in range(n):
                for j in range(n):
                    if not self.running: raise InterruptedError("Calculation stopped during Ricci scalar summation")
                    R_scalar_expr += g_inv[i, j] * R[i, j]
            print("% Simplifying Ricci scalar...")
            R_scalar = sp.simplify(R_scalar_expr)
            self.pretty_print_tensor_latex(R_scalar, "R", []) 
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after Ricci scalar")

            # --- Einstein Tensor --- 
            self.update_status("Calculating Einstein tensor...", 70)
            self.print_section_header("Einstein Tensor G_{\\mu\\nu}")
            print("% Calculating G_{\\mu\\nu} = R_{\\mu\\nu} - (1/2) * R * g_{\\mu\\nu}...\n")
            print("% Simplifying Einstein tensor...")
            Einstein_T = sp.simplify(R - sp.Rational(1, 2) * R_scalar * g)
            indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(Einstein_T, "G", indices)
            print("% Calculation of Einstein tensor finished.")
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after Einstein tensor")

            # --- Mixed Einstein Tensor --- 
            self.update_status("Calculating mixed Einstein tensor G^{\\mu}_{\\nu}...", 80)
            self.print_section_header("Mixed Einstein Tensor G^{\\mu}_{\\nu}")
            print("% Calculating G^{\\mu}_{\\nu} = g^{\\mu\\rho} * G_{\\rho\\nu}...\n")
            print("% Simplifying mixed Einstein tensor...")
            G_mixed = sp.simplify(g_inv * Einstein_T)
            mixed_indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(G_mixed, "G^", mixed_indices)
            print("% Calculation of mixed Einstein tensor finished.")
            self.print_separator()
            if not self.running: raise InterruptedError("Calculation stopped after mixed Einstein tensor")

            # --- Covariant Divergence --- 
            self.update_status("Calculating covariant divergence...", 90)
            self.print_section_header("Covariant Divergence \\nabla_\\nu G^{\\mu\\nu}")
            print("% Calculating covariant divergence (using standard formula)...\n")
            print("% Formula: \\nabla_\\nu G^{\\mu\\nu} = \\partial_\\nu G^{\\mu\\nu} + \\Gamma^{\\mu}_{\\lambda\\nu} G^{\\lambda\\nu} + \\Gamma^{\\nu}_{\\lambda\\nu} G^{\\mu\\lambda}\n")
            div_G = sp.Matrix.zeros(n, 1)
            for mu in range(n):
                if not self.running: raise InterruptedError(f"Calculation stopped at divergence for \\mu={{{mu}}}")
                current_progress = 90 + ((mu + 1) / n * 10)
                self.update_status(f"Calculating cov. divergence (μ={mu+1}/{n})...", current_progress)
                print(f"% Calculating divergence component for \\mu={{{mu}}}...")
                
                # ∇_ν G^μν = ∂_ν G^μν + Γ^μ_λν G^λν + Γ^ν_λν G^μλ
                term1_div = sp.sympify(0)
                term2_div = sp.sympify(0)
                term3_div = sp.sympify(0)
                
                # print(f"%   Summing terms for μ={{{mu}}}") # Too verbose
                for nu in range(n):
                    if not self.running: raise InterruptedError(f"Calculation stopped at divergence for \\mu={{{mu}}}, ν={{{nu}}}")
                    # Term 1: ∂_ν G^μν (sum over ν)
                    term1_div += sp.diff(G_mixed[mu, nu], coords[nu])
                    
                    for lam in range(n): # lambda index
                        if not self.running: raise InterruptedError(f"Calculation stopped at divergence for \\mu={{{mu}}}, ν={{{nu}}}, λ={{{lam}}}")
                        # Term 2: Γ^μ_λν G^λν (sum over λ, ν)
                        term2_div += Gamma[mu][lam][nu] * G_mixed[lam, nu]
                        # Term 3: Γ^ν_λν G^μλ (sum over λ, ν)
                        term3_div += Gamma[nu][lam][nu] * G_mixed[mu, lam]
                
                # print(f"%     Sum(∂_ν G^{{{mu}}}ν) = {sp.latex(term1_div)}") # Too verbose
                # print(f"%     Sum(Γ^{{{mu}}}_λν G^λν) = {sp.latex(term2_div)}") # Too verbose
                # print(f"%     Sum(Γ^ν_λν G^{{{mu}}}λ) = {sp.latex(term3_div)}") # Too verbose
                
                expr = term1_div + term2_div + term3_div
                # print(f"%   Resulting divergence expression (before simplify) for μ={{{mu}}}: {sp.latex(expr)}") # Too verbose
                
                print(f"%   Simplifying divergence expression for \\mu={{{mu}}}...")
                div_G[mu] = sp.simplify(expr)
             
            # Print final divergence results
            self.print_section_header("Result - Covariant Divergence \\nabla_\\nu G^{\\mu\\nu}")
            div_indices = [(i,) for i in range(n)] # Indices for a vector
            self.pretty_print_tensor_latex(div_G, "\\nabla_\\nu G^", div_indices)
            print("% Calculation of covariant divergence finished.")
            self.print_separator()
            
            self.update_status("Calculation finished successfully", 100)
            self.print_section_header("Calculation Finished Successfully")
            calculation_successful = True
            
        except InterruptedError as e:
            print(f"\n% !!! CALCULATION STOPPED BY USER !!!")
            print(f"% Reason: {str(e)}")
            # Status label is updated in finish_calculation
        except (SyntaxError, ValueError, TypeError, IndexError, AttributeError) as e:
            # Catch input processing errors or calculation errors
            print(f"\n% !!! INPUT or CALCULATION ERROR !!!")
            error_msg = str(e)
            print(f"% Error: {error_msg}")
            # Add traceback if not already in the message (SyntaxError might have it)
            if "Traceback" not in error_msg:
                tb_lines = traceback.format_exc().splitlines()
                print("% Traceback:")
                for line in tb_lines:
                    print(f"% {line}")
            # Status label is updated in finish_calculation
        except Exception as e:
            # Catch-all for unexpected errors
            print(f"\n% !!! UNEXPECTED ERROR DURING CALCULATION !!!")
            print(f"% Error: {str(e)}")
            tb_lines = traceback.format_exc().splitlines()
            print("% Traceback:")
            for line in tb_lines:
                print(f"% {line}")
            # Status label is updated in finish_calculation
        finally:
            # Restore standard output
            if old_stdout:
                sys.stdout = old_stdout
            # Update status if calculation failed and not already stopped/errored
            current_status = self.status_label.cget("text") if self.root.winfo_exists() else ""
            if not calculation_successful and self.running: # self.running is False if stopped
                 current_progress = self.progress_var.get()
                 # Avoid race condition if window closed during calculation
                 if self.root.winfo_exists(): 
                      self.update_status(f"Calculation failed (see output)", current_progress if current_progress > 0 else 0)
            # finish_calculation will be called automatically via check_calculation_status
            
    def finish_calculation(self):
        # This method is called after the thread finishes (even on error/stop)
        # Update status only if it wasn't already set by exception or success message
        if self.root.winfo_exists(): # Check if window is still valid
            current_status = self.status_label.cget("text")
            # Determine final status message if not already set
            final_status = current_status
            if "Successfully" not in current_status and "stopped" not in current_status and "Error" not in current_status and "failed" not in current_status:
                final_status = "Calculation ended (unknown state)"
            
            self.update_status(final_status, self.progress_var.get()) 
                 
            self.running = False # Ensure running flag is False
            # Re-enable buttons only if the window exists
            self.run_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.clear_button.config(state=tk.NORMAL)
        else:
            # Window closed, just ensure the flag is False
            self.running = False
        
if __name__ == "__main__":
    root = tk.Tk()
    app = EinsteinCalculatorApp(root)
    root.mainloop() 