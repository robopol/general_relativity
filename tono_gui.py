import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import threading
import sympy as sp
import queue
import sys
import io
import time
import traceback # Pre detailný výpis chýb

class RedirectText:
    def __init__(self, text_widget):
        self.output = text_widget
        self.queue = queue.Queue()
        self.updating = True
        self.after_id = None
        # Použijeme referenciu na metódu update_worker
        self.update_thread = threading.Thread(target=self.update_worker, daemon=True)
        self.update_thread.start()

    def write(self, string):
        # Dáme do fronty len ak vlákno stále beží
        if self.updating:
            self.queue.put(string)

    def update_worker(self):
        while self.updating:
            try:
                # Blokujeme s timeoutom, aby sme nezaťažovali CPU
                string = self.queue.get(block=True, timeout=0.1)
                # Plánujeme aktualizáciu v hlavnom vlákne Tkinter
                self.output.after(0, self.update_text, string)
                self.queue.task_done()
            except queue.Empty:
                # Ak je fronta prázdna, počkáme a skúsime znova
                time.sleep(0.05) 
            except Exception as e:
                # Vypíšeme chybu na stderr, aby sa nezobrazila v LaTeX výstupe
                print(f"Chyba v RedirectText.update_worker: {e}", file=sys.stderr)
                time.sleep(0.1)

    def update_text(self, string):
        # Táto metóda beží v hlavnom vlákne Tkinter
        try:
            # Získame referenciu na widget, ak existuje
            if self.output.winfo_exists():
                self.output.config(state=tk.NORMAL)
                self.output.insert(tk.END, string)
                self.output.see(tk.END) # Auto-scroll
                self.output.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Chyba pri aktualizácii textového poľa: {e}", file=sys.stderr)
    
    def flush(self):
        # Táto metóda je potrebná pre kompatibilitu s file-like objektmi
        pass

    def stop(self):
        # Nastavíme flag na False
        self.updating = False
        # Môžeme pridať None do fronty na odblokovanie get, ak by vlákno čakalo
        self.queue.put(None) 
        # Počkáme krátko na dokončenie vlákna (voliteľné)
        # self.update_thread.join(timeout=0.5)

class LatexOutputFormatter:
    """Trieda na formátovanie LaTeX výstupov"""
    
    @staticmethod
    def format_matrix(matrix):
        """Vytvorí LaTeX reťazec pre maticu"""
        if not isinstance(matrix, sp.Matrix):
            return sp.latex(matrix)
        # Použijeme bmatrix pre krajšie zobrazenie
        return sp.latex(matrix, mode='inline', mat_delim='', mat_str='bmatrix')
    
    @staticmethod
    def format_tensor_component(name, indices, expr):
        """Formátuje komponent tenzora s indexmi do LaTeXu"""
        indices_str = "".join(str(idx) for idx in indices)
        name_str = name
        is_vector_or_scalar_or_divergence = False
        
        # Špeciálne formátovanie pre G^μ_ν a ∇_ν G^μν
        if name == "G^":
            if len(indices) == 2:
                 name_str = f"G^{{{indices[0]}}}_{{{indices[1]}}}"
            else: 
                 name_str = f"G^{{{indices_str}}}_?"
        elif name == "\\nabla_\\nu G^":
            if len(indices) == 1:
                name_str = f"\\nabla_\\nu G^{{{indices[0]}}}{{\\nu}}"
                is_vector_or_scalar_or_divergence = True
            else: 
                name_str = f"\\nabla_\\nu G^{{{indices_str}}}?"
        elif len(indices) == 2: # Predpokladáme R_μν, G_μν
            name_str = f"{name}_{{{indices_str}}}"
        elif len(indices) == 1: # Predpokladáme vektor
            name_str = f"{name}_{{{indices_str}}}" 
            is_vector_or_scalar_or_divergence = True
        elif len(indices) == 0: # Skalár
             name_str = name
             is_vector_or_scalar_or_divergence = True
        else: # Viac indexov?
             name_str = f"{name}_{{{indices_str}}}"

        header = f"{name_str} = "
        
        # Generovanie LaTeX kódu
        expr_latex = sp.latex(expr)
        
        # Pridáme nový riadok len pre tenzory druhého rádu (matice) pre lepšiu čitateľnosť
        # Pre vektory, skaláry a divergenciu necháme na jednom riadku.
        newline = " \\\\ \n" if not is_vector_or_scalar_or_divergence else " " 
        
        # Výsledný LaTeX reťazec
        return f"{header}{expr_latex}{newline}\n"

class EinsteinCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Všeobecný Kalkulátor Einsteinových Tenzorov (LaTeX Výstup)")
        # Zväčšíme okno kvôli textovému poľu pre metriku
        self.root.geometry("1200x800") 
        
        self.running = False
        self.calculation_thread = None
        self.progress_var = tk.DoubleVar(value=0)
        
        # Nastavenie fontu pre textové pole
        self.setup_fonts()
        
        self.create_widgets()
        
        # Nastavenie predvolenej Kerrovej metriky
        self.set_kerr_metric_default()
        
        # Zavrieme stdout redirector pri zatváraní okna
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def on_closing(self):
        print("Zatváram aplikáciu...")
        if self.stdout_redirector:
            self.stdout_redirector.stop()
        # Zastavíme aj prípadne bežiaci výpočet
        if self.running:
             self.stop_calculation(force=True)
        self.root.destroy()

    def setup_fonts(self):
        # Nastavenie monospace fontu pre lepšie zobrazenie LaTeX kódu a definície metriky
        font_family = "Consolas" if "Consolas" in font.families() else "Courier"
        self.code_font = font.Font(family=font_family, size=10)
        
    def create_widgets(self):
        # --- Hlavný Frame --- 
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1) # Stĺpec pre vstupy
        main_frame.columnconfigure(1, weight=3) # Stĺpec pre výstup
        main_frame.rowconfigure(1, weight=1) # Riadok pre výstup expanduje

        # --- Frame pre Vstupy (ľavá strana) --- 
        input_panel = ttk.Frame(main_frame, padding="5")
        input_panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        input_panel.rowconfigure(3, weight=1) # Riadok pre metriku expanduje

        # --- Vstupné Parametre --- 
        param_frame = ttk.LabelFrame(input_panel, text="Definícia Časopriestoru", padding="10")
        param_frame.grid(row=0, column=0, sticky="new", pady=(0, 10))
        param_frame.columnconfigure(1, weight=1)

        # Súradnice
        ttk.Label(param_frame, text="Súradnice:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.coords_var = tk.StringVar(value="t, r, theta, phi")
        ttk.Entry(param_frame, textvariable=self.coords_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        
        # Symboly
        ttk.Label(param_frame, text="Symboly:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.symbols_var = tk.StringVar(value="M, a")
        ttk.Entry(param_frame, textvariable=self.symbols_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(param_frame, text="(napr. M, a, k, ...)").grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=0)

        # --- Metrika --- 
        metric_frame = ttk.LabelFrame(input_panel, text="Metrický Tenzor g (Python List)", padding="10")
        metric_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        metric_frame.rowconfigure(0, weight=1)
        metric_frame.columnconfigure(0, weight=1)

        self.metric_text = scrolledtext.ScrolledText(metric_frame, wrap=tk.WORD, height=15, 
                                                    font=self.code_font)
        self.metric_text.grid(row=0, column=0, sticky="nsew")
        # Pridáme tooltip alebo label s inštrukciou
        ttk.Label(metric_frame, text="Zadajte ako zoznam zoznamov, napr. [[-1,0],[0,1]]. Použite 'sp.' pre sympy funkcie.").grid(row=1, column=0, sticky="w", pady=(5,0))
        # Nová inštrukcia pre `exec`
        ttk.Label(metric_frame, text="Výsledný zoznam priraďte do premennej `metric_matrix`.", foreground="blue").grid(row=2, column=0, sticky="w", pady=(2,0))

        # --- Tlačidlá a Progress Bar (pod vstupmi) --- 
        control_frame = ttk.Frame(input_panel, padding="5")
        control_frame.grid(row=4, column=0, sticky="sew")

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=(10, 5), anchor="w")
        
        self.run_button = ttk.Button(button_frame, text="Spustiť výpočet", command=self.run_calculation)
        self.run_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(button_frame, text="Zastaviť", command=self.stop_calculation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.clear_button = ttk.Button(button_frame, text="Vyčistiť výstup", command=self.clear_output)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        progress_frame = ttk.Frame(control_frame)
        progress_frame.pack(fill=tk.X, pady=5, anchor="w")
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, expand=True)
        
        self.status_label = ttk.Label(progress_frame, text="Pripravené")
        self.status_label.pack(anchor="w")

        # --- Frame pre Výstup (pravá strana) --- 
        output_panel = ttk.Frame(main_frame, padding="5")
        output_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        output_panel.rowconfigure(0, weight=1)
        output_panel.columnconfigure(0, weight=1)

        output_frame = ttk.LabelFrame(output_panel, text="Výsledky (LaTeX kód)", padding="10")
        output_frame.grid(row=0, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, 
                                                  state=tk.DISABLED, font=self.code_font)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        ttk.Label(output_frame, text="Skopírujte tento kód a vložte ho do LaTeX editora/renderera.").grid(row=1, column=0, sticky="w", pady=(5,0))
                
        # Presmerovanie štandardného výstupu
        # Inicializujeme až po vytvorení output_text
        self.stdout_redirector = RedirectText(self.output_text)
            
    def set_kerr_metric_default(self):
        """Nastaví Kerrovu metriku ako predvolený text"""
        self.coords_var.set("t, r, theta, phi")
        self.symbols_var.set("M, a") # Späť na M, a pre Kerr
        
        kerr_metric_string = (
            "# Kerrova metrika v Boyer-Lindquist súradniciach\n"
            "# Potrebné symboly: M, a (už definované vyššie)\n"
            "rho2 = r**2 + a**2 * sp.cos(theta)**2\n"
            "Delta = r**2 - 2*M*r + a**2\n\n"
            "# Výsledný zoznam musí byť priradený do premennej 'metric_matrix'\n"
            "metric_matrix = [\n"
            "  [-(1 - 2*M*r / rho2), 0, 0, - (2 * M * a * r * sp.sin(theta)**2) / rho2],\n"
            "  [0, rho2 / Delta, 0, 0],\n"
            "  [0, 0, rho2, 0],\n"
            "  [- (2 * M * a * r * sp.sin(theta)**2) / rho2, 0, 0, ( (r**2 + a**2)**2 - a**2 * Delta * sp.sin(theta)**2 ) * sp.sin(theta)**2 / rho2]\n"
            "]"
        )
        # Vymažeme existujúci text pred vložením
        self.metric_text.delete(1.0, tk.END)
        self.metric_text.insert(tk.END, kerr_metric_string)

    def update_status(self, text, progress=None):
        # Aktualizácia GUI vždy cez after() z hlavného vlákna
        def update_gui():
            if self.status_label.winfo_exists():
                 self.status_label.config(text=text)
            if progress is not None and self.progress_bar.winfo_exists():
                self.progress_var.set(progress)
            # self.root.update_idletasks() # update_idletasks môže byť problematické
        self.root.after(0, update_gui)
    
    def clear_output(self):
        if self.output_text.winfo_exists():
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.config(state=tk.DISABLED)
        self.update_status("Výstup vyčistený", 0)
        
    def run_calculation(self):
        if self.running:
            messagebox.showwarning("Varovanie", "Výpočet už beží.")
            return
            
        # --- Získanie a validácia vstupov --- 
        coords_str = self.coords_var.get().strip()
        symbols_str = self.symbols_var.get().strip()
        metric_def_str = self.metric_text.get(1.0, tk.END).strip()

        if not coords_str:
             messagebox.showerror("Chyba vstupu", "Zadajte názvy súradníc (oddelené čiarkou).")
             return
        if not metric_def_str:
             messagebox.showerror("Chyba vstupu", "Zadajte definíciu metrického tenzora.")
             return

        # Vymazať starý výstup
        self.clear_output()
        
        # Nastaviť stavy tlačidiel
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.DISABLED)
        
        # Spustiť výpočet vo vlákne
        self.running = True
        self.progress_var.set(0)
        # Odovzdáme vstupy ako argumenty vláknu
        self.calculation_thread = threading.Thread(target=self.perform_calculation, 
                                                 args=(coords_str, symbols_str, metric_def_str))
        self.calculation_thread.daemon = True
        self.calculation_thread.start()
        
        # Pravidelná kontrola stavu výpočtu
        self.root.after(100, self.check_calculation_status)
        
    def check_calculation_status(self):
        # Ak vlákno stále beží a GUI existuje
        if self.running and self.calculation_thread and self.calculation_thread.is_alive():
             if self.root.winfo_exists(): # Skontrolujeme, či okno ešte existuje
                 self.root.after(100, self.check_calculation_status)
        else:
            # Vlákno skončilo (normálne, chybou alebo bolo zastavené)
            # Ak okno stále existuje, aktualizujeme GUI
            if self.root.winfo_exists():
                self.finish_calculation()
        
    def stop_calculation(self, force=False):
        if not self.running and not force:
            return
            
        if self.running:
             print("\n% Prijatý pokyn na zastavenie...\n") # Pridaný výpis
             self.running = False # Nastavíme flag, aby sa cykly ukončili
             self.update_status("Zastavovanie výpočtu...", self.progress_var.get())
        elif force and self.calculation_thread and self.calculation_thread.is_alive():
             # Toto je nútené zastavenie pri zatváraní okna, vlákno nemusí byť running
             self.running = False
             print("\n% Nútené zastavenie výpočtu pri zatváraní okna...\n")

        # Vlákno by sa malo ukončiť samo po kontrole self.running
        # finish_calculation sa zavolá automaticky cez check_calculation_status
            
    def print_separator(self):
        """Vytlačí jednoduchý oddeľovač pre LaTeX výstup"""
        print("\n%-----------------------------------------------------%\n")
    
    def print_section_header(self, text):
        """Vytlačí nadpis sekcie ako LaTeX komentár"""
        print(f"\n% ===== {text} ===== %\n")
    
    def pretty_print_tensor_latex(self, tensor, name, indices_list):
        """Vytlačí tenzor ako sériu LaTeX výrazov"""
        for indices in indices_list:
            if not self.running: # Kontrola pred každým komponentom
                raise InterruptedError("Výpočet bol zastavený používateľom počas výpisu")
                
            if len(indices) == 2:
                i, j = indices
                # Získanie LaTeX výrazu pre komponent
                print(f"% Počítam/Vypisujem komponent {name} s indexmi ({i},{j})") # Detailnejší výpis
                latex_expr = LatexOutputFormatter.format_tensor_component(name, [i, j], tensor[i, j])
                print(latex_expr)
            elif len(indices) == 1:
                 i = indices[0]
                 print(f"% Počítam/Vypisujem komponent {name} s indexom ({i})") # Detailnejší výpis
                 latex_expr = LatexOutputFormatter.format_tensor_component(name, [i], tensor[i])
                 print(latex_expr)
            # Pre skaláry (len názov)
            elif len(indices) == 0:
                print(f"% Vypisujem skalár {name}")
                latex_expr = LatexOutputFormatter.format_tensor_component(name, [], tensor)
                print(latex_expr)

    # Výpočet teraz prijíma vstupy ako argumenty
    def perform_calculation(self, coords_str, symbols_str, metric_def_str):
        calculation_successful = False
        local_namespace = {'sp': sp} # Základný namespace pre eval
        coords = []
        g = None
        n = 0
        
        try:
            # Presmerovanie stdout na náš textový widget
            old_stdout = sys.stdout
            sys.stdout = self.stdout_redirector
            
            self.update_status("Spracovávam vstupy...", 1)
            
            # --- Spracovanie súradníc --- 
            try:
                coord_names = [s.strip() for s in coords_str.split(',') if s.strip()]
                if not coord_names:
                    raise ValueError("Neboli zadané žiadne názvy súradníc.")
                # Vytvorenie symbolov pre súradnice
                coords_syms = sp.symbols(coord_names, real=True)
                # Ak je len jedna súradnica, symbols vráti symbol, nie tuple
                coords = list(coords_syms) if isinstance(coords_syms, (tuple, list)) else [coords_syms]
                n = len(coords)
                if n == 0: raise ValueError("Počet súradníc musí byť > 0.")
                # Pridanie súradníc do namespace pre eval
                for name, sym in zip(coord_names, coords):
                    local_namespace[name] = sym
                print(f"% Súradnice ({n}D): {', '.join(coord_names)}")
            except Exception as e:
                raise ValueError(f"Chyba pri spracovaní súradníc '{coords_str}': {e}")
            
            # --- Spracovanie symbolov --- 
            try:
                if symbols_str: # Ak boli zadané symboly
                    symbol_names = [s.strip() for s in symbols_str.split(',') if s.strip()]
                    if symbol_names:
                        # Predpokladáme, že sú reálne a kladné (bežné pre fyzikálne konštanty)
                        symbols_obj = sp.symbols(symbol_names, real=True, positive=True)
                        # Uloženie symbolov do namespace
                        current_symbols = list(symbols_obj) if isinstance(symbols_obj, (tuple, list)) else [symbols_obj]
                        for name, sym in zip(symbol_names, current_symbols):
                            local_namespace[name] = sym
                        print(f"% Definované symboly: {', '.join(symbol_names)}")
                    else:
                        print("% Neboli definované žiadne dodatočné symboly.")
                else:
                     print("% Neboli definované žiadne dodatočné symboly.")
            except Exception as e:
                 raise ValueError(f"Chyba pri spracovaní symbolov '{symbols_str}': {e}")

            # --- Spracovanie definície metriky --- 
            self.update_status("Spracovávam definíciu metriky...", 5)
            self.print_section_header("Spracovanie Metriky")
            print(f"% Pokúšam sa spracovať definíciu metriky...\n")
            try:
                # Odstránime komentáre z definície metriky pre bezpečnejší eval
                metric_code_lines = []
                for line in metric_def_str.splitlines():
                    stripped_line = line.split('#', 1)[0].strip()
                    if stripped_line:
                        metric_code_lines.append(stripped_line)
                metric_code = '\n'.join(metric_code_lines)
                
                # Vykonáme kód definície metriky pomocou exec()
                # Definuje premenné (napr. rho2, Delta) a metric_matrix v local_namespace
                exec(metric_code, {'sp': sp, '__builtins__': {}}, local_namespace)
                
                # Získame výslednú maticu z namespace
                if 'metric_matrix' not in local_namespace:
                    raise NameError("Premenná `metric_matrix` nebola definovaná v kóde metriky.")
                
                metric_input = local_namespace['metric_matrix']
                
                # Prevod na SymPy Matrix, ak to nie je už Matrix
                if isinstance(metric_input, list):
                    g = sp.Matrix(metric_input)
                elif isinstance(metric_input, sp.Matrix):
                    g = metric_input
                else:
                    raise TypeError("Definícia metriky musí byť Python zoznam zoznamov alebo sympy.Matrix.")
                
                # Validácia rozmerov matice
                if g.shape != (n, n):
                     raise ValueError(f"Rozmery metriky {g.shape} nezodpovedajú počtu súradníc ({n}).")
                     
                print("% Definícia metriky úspešne spracovaná.")
                
            except Exception as e:
                # Vypíšeme detailnú chybu vrátane potenciálneho tracebacku z eval
                error_msg = f"Chyba pri spracovaní definície metriky: {e}\n" \
                            f"Skontrolujte syntax, názvy premenných a použitie 'sp.'.\n" \
                            f"Zadaná definícia:\n{metric_def_str}"
                # Získame traceback, ak je dostupný
                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                error_msg += "\n% Traceback (z eval):\n% " + "% ".join(tb_lines) # Formátujeme ako komentáre
                raise SyntaxError(error_msg)
            
            # === Začiatok výpočtov ===
            if not self.running: raise InterruptedError("Výpočet zastavený pred začatím výpočtov")
            
            self.print_section_header(f"Metrický tenzor g (zadaný {n}x{n})")
            print(LatexOutputFormatter.format_matrix(g))
            self.print_separator()
            
            # --- Inverzná metrika --- 
            self.update_status("Počítam inverznú metriku", 20)
            self.print_section_header("Inverzná metrika g^{\\mu\\nu}")
            print("% Počítam inverznú metriku g^{\\mu\\nu} = g^{-1}...\n")
            g_inv = sp.simplify(g.inv())
            print(LatexOutputFormatter.format_matrix(g_inv))
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po inverznej metrike")

            # --- Christoffelove symboly --- 
            self.update_status("Počítam Christoffelove symboly", 30)
            self.print_section_header("Christoffelove symboly \\Gamma^{\\rho}_{\\mu\\nu}")
            print("% Počítam Christoffelove symboly... (Používam sp.cancel() pre rýchlosť)\n") # Info o optimalizácii
            Gamma = [[[sp.sympify(0) for _ in range(n)] for _ in range(n)] for _ in range(n)]
            for rho in range(n):
                for mu in range(n):
                    for nu in range(n):
                        if not self.running: raise InterruptedError(f"Výpočet zastavený pri \\Gamma^{{{rho}}}_{{{mu}}}{{{nu}}}")
                        # Detailný výpis pre každý symbol môže byť príliš veľa, zvážiť vypnutie/zapnutie
                        # print(f"% Počítam \\Gamma^{{{rho}}}_{{{mu}}}{{{nu}}}...") 
                        sum_val = sp.sympify(0)
                        for lam in range(n): # lambda index
                             term = g_inv[rho, lam] * (sp.diff(g[lam, mu], coords[nu]) +
                                                     sp.diff(g[lam, nu], coords[mu]) -
                                                     sp.diff(g[mu, nu], coords[lam]))
                             sum_val += term
                        # Použijeme sp.cancel() namiesto sp.simplify() pre zrýchlenie
                        # Výsledok nemusí byť plne zjednodušený, ale výpočet bude rýchlejší.
                        Gamma[rho][mu][nu] = sp.cancel(sp.Rational(1, 2) * sum_val) 
                progress = 30 + ((rho + 1) / n * 15)
                self.update_status(f"Počítam Christoffelove symboly (ρ={rho+1}/{n})", progress)
            print("% Výpočet Christoffelových symbolov dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Christoffelových symboloch")

            # --- Ricciho tenzor --- 
            self.update_status("Počítam Ricciho tenzor", 45)
            self.print_section_header("Ricciho tenzor R_{\\mu\\nu}")
            print("% Počítam Ricciho tenzor (podľa štandardného vzorca)...\n")
            R = sp.Matrix.zeros(n, n)
            for mu in range(n):
                for nu in range(n):
                    if not self.running: raise InterruptedError(f"Výpočet zastavený pri R_{{{mu}}}{{{nu}}}")
                    print(f"% Počítam R_{{{mu}}}{{{nu}}}...")
                    
                    # R_μν = ∂_ρ Γ^ρ_μν - ∂_ν Γ^ρ_μρ + Γ^ρ_μν Γ^σ_ρσ - Γ^σ_μρ Γ^ρ_νσ
                    term1 = sum(sp.diff(Gamma[rho][mu][nu], coords[rho]) for rho in range(n))
                    term2 = sum(sp.diff(Gamma[rho][mu][rho], coords[nu]) for rho in range(n))
                    term3 = sum(sum(Gamma[rho][mu][nu] * Gamma[sigma][rho][sigma] for sigma in range(n)) for rho in range(n))
                    term4 = sum(sum(Gamma[sigma][mu][rho] * Gamma[rho][nu][sigma] for rho in range(n)) for sigma in range(n))
                    
                    R[mu, nu] = sp.simplify(term1 - term2 + term3 - term4)
                    # Vypisovať každý komponent Ricciho tenzora môže byť veľmi zdĺhavé
                    # print(f"% R_{{{mu}}}{{{nu}}} = {sp.latex(R[mu, nu])}\n") 
                progress = 45 + ((mu + 1) / n * 15)
                self.update_status(f"Počítam Ricciho tenzor (μ={mu+1}/{n})", progress)
            # Vypíšeme celý Ricciho tenzor naraz
            print("% Ricciho Tenzor R_{\\mu\\nu}:")
            print(LatexOutputFormatter.format_matrix(R))
            print("% Výpočet Ricciho tenzora dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Ricciho tenzore")

            # --- Ricciho skalár --- 
            self.update_status("Počítam Ricciho skalár", 60)
            self.print_section_header("Ricciho skalár R")
            print("% Počítam Ricciho skalár R = g^{\\mu\\nu} R_{\\mu\\nu}...\n")
            R_scalar_expr = sp.sympify(0)
            for i in range(n):
                for j in range(n):
                    if not self.running: raise InterruptedError("Výpočet zastavený pri sčítaní Ricciho skalára")
                    R_scalar_expr += g_inv[i, j] * R[i, j]
            print("% Zjednodušujem Ricciho skalár...")
            R_scalar = sp.simplify(R_scalar_expr)
            self.pretty_print_tensor_latex(R_scalar, "R", []) # Použijeme formátovač pre skalár
            # print(sp.latex(R_scalar)) # Starý spôsob
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Ricciho skalári")

            # --- Einsteinov tenzor --- 
            self.update_status("Počítam Einsteinov tenzor", 70)
            self.print_section_header("Einsteinov tenzor G_{\\mu\\nu}")
            print("% Počítam Einsteinov tenzor G_{\\mu\\nu} = R_{\\mu\\nu} - (1/2) * R * g_{\\mu\\nu}...\n")
            print("% Zjednodušujem Einsteinov tenzor...")
            Einstein_T = sp.simplify(R - sp.Rational(1, 2) * R_scalar * g)
            indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(Einstein_T, "G", indices)
            print("% Výpočet Einsteinovho tenzora dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Einsteinovom tenzore")

            # --- Zmiešané zložky Einsteinovho tenzora --- 
            self.update_status("Počítam zmiešané zložky G^{\\mu}_{\\nu}", 80)
            self.print_section_header("Zmiešané zložky Einsteinovho tenzora G^{\\mu}_{\\nu}")
            print("% Počítam zmiešané zložky G^{\\mu}_{\\nu} = g^{\\mu\\rho} * G_{\\rho\\nu}...\n")
            print("% Zjednodušujem zmiešané zložky...")
            G_mixed = sp.simplify(g_inv * Einstein_T)
            mixed_indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(G_mixed, "G^", mixed_indices)
            print("% Výpočet zmiešaných zložiek dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po zmiešaných zložkách")

            # --- Kovariantná divergencia --- 
            self.update_status("Počítam kovariantnú divergenciu", 90)
            self.print_section_header("Kovariantná divergencia \\nabla_\\nu G^{\\mu\\nu}")
            print("% Počítam kovariantnú divergenciu (podľa štandardného vzorca)...\n")
            print("% Vzorec: \\nabla_\\nu G^{\\mu\\nu} = \\partial_\\nu G^{\\mu\\nu} + \\Gamma^{\\mu}_{\\lambda\\nu} G^{\\lambda\\nu} + \\Gamma^{\\nu}_{\\lambda\\nu} G^{\\mu\\lambda}\n")
            div_G = sp.Matrix.zeros(n, 1)
            for mu in range(n):
                if not self.running: raise InterruptedError(f"Výpočet zastavený pri divergencii pre \\mu={{{mu}}}")
                self.update_status(f"Počítam kov. divergenciu (μ={mu+1}/{n})", 90 + ((mu + 1) / n * 10))
                print(f"% Počítam zložku divergencie pre \\mu={{{mu}}}...")
                
                # ∇_ν G^μν = ∂_ν G^μν + Γ^μ_λν G^λν + Γ^ν_λν G^μλ
                term1_div = sp.sympify(0)
                term2_div = sp.sympify(0)
                term3_div = sp.sympify(0)
                
                print(f"%   Sčítavam členy pre \\mu={{{mu}}}")
                for nu in range(n):
                    if not self.running: raise InterruptedError(f"Výpočet zastavený pri divergencii pre \\mu={{{mu}}}, ν={{{nu}}}")
                    # Člen 1: ∂_ν G^μν (derivujeme a sčítame cez ν)
                    term1_div += sp.diff(G_mixed[mu, nu], coords[nu])
                    
                    for lam in range(n): # lambda index
                        if not self.running: raise InterruptedError(f"Výpočet zastavený pri divergencii pre \\mu={{{mu}}}, ν={{{nu}}}, λ={{{lam}}}")
                        # Člen 2: Γ^μ_λν G^λν (sčítame cez λ a ν)
                        term2_div += Gamma[mu][lam][nu] * G_mixed[lam, nu]
                        # Člen 3: Γ^ν_λν G^μλ (sčítame cez λ a ν)
                        term3_div += Gamma[nu][lam][nu] * G_mixed[mu, lam]
                
                print(f"%     Sum(∂_ν G^{{{mu}}}ν) = {sp.latex(term1_div)}")
                print(f"%     Sum(Γ^{{{mu}}}_λν G^λν) = {sp.latex(term2_div)}")
                print(f"%     Sum(Γ^ν_λν G^{{{mu}}}λ) = {sp.latex(term3_div)}")
                
                expr = term1_div + term2_div + term3_div
                print(f"%   Výsledný výraz pre divergenciu (pred simplify) pre \\mu={{{mu}}}: {sp.latex(expr)}")
                
                print(f"%   Zjednodušujem výraz pre divergenciu pre \\mu={{{mu}}}...")
                div_G[mu] = sp.simplify(expr)
                # Výpis jednotlivej zložky sa robí v pretty_print_tensor_latex
                # print(f"%   Výsledok divergencie pre \\mu={{{mu}}}: {sp.latex(div_G[mu])}\n")
             
            # Výpis finálnych výsledkov divergencie
            self.print_section_header("Výsledok - Kovariantná divergencia \\nabla_\\nu G^{\\mu\\nu}")
            div_indices = [(i,) for i in range(n)] # Indexy pre vektor
            self.pretty_print_tensor_latex(div_G, "\\nabla_\\nu G^", div_indices)
            print("% Výpočet kovariantnej divergencie dokončený.")
            self.print_separator()
            
            self.update_status("Výpočet dokončený", 100)
            self.print_section_header("Výpočet úspešne dokončený")
            calculation_successful = True
            
        except InterruptedError as e:
            print(f"\n% !!! VÝPOČET PRERUŠENÝ POUŽÍVATEĽOM !!!")
            print(f"% Dôvod: {str(e)}")
            # Stavový label sa aktualizuje vo finish_calculation
        except (SyntaxError, ValueError, TypeError, IndexError, AttributeError) as e:
            # Zachytávame chyby pri spracovaní vstupov alebo výpočtoch
            print(f"\n% !!! CHYBA VSTUPU ALEBO VÝPOČTU !!!")
            error_msg = str(e)
            print(f"% Chyba: {error_msg}")
            # Pridáme traceback, ak nie je už v správe (SyntaxError ho zvykne mať)
            if "Traceback" not in error_msg:
                tb_lines = traceback.format_exc().splitlines()
                print("% Traceback:")
                for line in tb_lines:
                    print(f"% {line}")
            # Stavový label sa aktualizuje vo finish_calculation
        except Exception as e:
            # Všeobecná chyba
            print(f"\n% !!! NEOČAKÁVANÁ CHYBA PRI VÝPOČTE !!!")
            print(f"% Chyba: {str(e)}")
            tb_lines = traceback.format_exc().splitlines()
            print("% Traceback:")
            for line in tb_lines:
                print(f"% {line}")
            # Stavový label sa aktualizuje vo finish_calculation
        finally:
            # Obnova štandardného výstupu
            sys.stdout = old_stdout
            # Ak výpočet neskončil úspešne, povieme to
            if not calculation_successful and self.running: # self.running je False ak bolo prerušené
                 current_progress = self.progress_var.get()
                 self.update_status(f"Výpočet zlyhal (pozri výstup)", current_progress if current_progress > 0 else 0)
            # Finish calculation sa zavolá automaticky cez check_calculation_status
            
    def finish_calculation(self):
        # Táto metóda sa volá po skončení vlákna (aj pri chybe/prerušení)
        # Aktualizujeme stav len ak to neurobila už výnimka alebo úspešný koniec
        current_status = self.status_label.cget("text")
        if "Výpočet úspešne dokončený" not in current_status and "zastavený" not in current_status and "Chyba" not in current_status and "zlyhal" not in current_status:
             # Ak vlákno skončilo bez jasnej správy, asi bola chyba alebo prerušenie skôr
             self.update_status("Výpočet ukončený (neznámy stav)", self.progress_var.get())
             
        self.running = False # Uistíme sa, že je False
        # Povolíme tlačidlá len ak okno existuje
        if self.root.winfo_exists():
            self.run_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.clear_button.config(state=tk.NORMAL)
        
if __name__ == "__main__":
    root = tk.Tk()
    app = EinsteinCalculatorApp(root)
    root.mainloop() 
