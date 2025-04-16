import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import threading
import sympy as sp
import queue
import sys
import io
import time

class RedirectText:
    def __init__(self, text_widget):
        self.output = text_widget
        self.queue = queue.Queue()
        self.updating = True
        self.after_id = None
        threading.Thread(target=self.update_worker, daemon=True).start()

    def write(self, string):
        self.queue.put(string)

    def update_worker(self):
        while self.updating:
            try:
                string = self.queue.get(timeout=0.1)
                self.output.after(10, self.update_text, string)
                self.queue.task_done()
            except queue.Empty:
                time.sleep(0.01)
            except Exception as e:
                print(f"% Chyba v update_worker: {e}")
                time.sleep(0.1)

    def update_text(self, string):
        try:
            self.output.config(state=tk.NORMAL)
            self.output.insert(tk.END, string)
            self.output.see(tk.END)
            self.output.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Chyba pri aktualizácii textu: {e}", file=sys.__stderr__)
    
    def flush(self):
        pass

    def stop(self):
        self.updating = False

class LatexOutputFormatter:
    """Trieda na formátovanie LaTeX výstupov"""
    
    @staticmethod
    def format_matrix(matrix):
        """Vytvorí LaTeX reťazec pre maticu"""
        if not isinstance(matrix, sp.Matrix):
            return sp.latex(matrix)
        return sp.latex(matrix)
    
    @staticmethod
    def format_tensor_component(name, indices, expr):
        """Formátuje komponent tenzora s indexmi do LaTeXu"""
        indices_str = ",".join(str(idx) for idx in indices)
        if len(indices) == 2:  # Ak je to 2D tenzor (matica)
            row, col = indices
            # Používame syntax pre dolné indexy
            header = f"{name}_{{{row}{col}}} = "
        elif len(indices) == 1: # Pre vektory alebo 1D tenzory
            idx = indices[0]
            header = f"{name}^{{{idx}}} = " # Horný index pre kovariantnú divergenciu
        else:  # Pre skaláry
            header = f"{name} = "
        
        # Generovanie LaTeX kódu
        expr_latex = sp.latex(expr)
        
        # Výsledný LaTeX reťazec
        return f"{header} {expr_latex}\n\n"

class EinsteinCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Kalkulátor Einsteinových tenzorov (LaTeX Výstup)")
        self.root.geometry("1000x700")
        
        self.running = False
        self.calculation_thread = None
        self.progress_var = tk.DoubleVar(value=0)
        
        # Nastavenie fontu pre textové pole (stále užitočné pre čitateľnosť kódu)
        self.setup_fonts()
        
        self.create_widgets()
        
    def setup_fonts(self):
        # Nastavenie monospace fontu pre lepšie zobrazenie LaTeX kódu
        font_family = "Consolas" if "Consolas" in font.families() else "Courier"
        self.code_font = font.Font(family=font_family, size=10)
        
    def create_widgets(self):
        # Hlavný frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Vstupné parametre
        input_frame = ttk.LabelFrame(main_frame, text="Vstupné parametre", padding="10")
        input_frame.pack(fill=tk.X, pady=5)
        
        # Ľavý a pravý stĺpec pre lepšie usporiadanie
        left_frame = ttk.Frame(input_frame)
        left_frame.grid(row=0, column=0, padx=10, sticky=tk.W)
        
        right_frame = ttk.Frame(input_frame)
        right_frame.grid(row=0, column=1, padx=10, sticky=tk.W)
        
        # Súradnice (t, r, theta, phi) - len na informáciu
        ttk.Label(left_frame, text="Súradnice:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Label(left_frame, text="t, r, theta, phi (automaticky definované)").grid(row=0, column=1, sticky=tk.W, pady=5)
        
        # k konštanta - v pôvodnom kóde je to symbolická premenná
        ttk.Label(left_frame, text="Symbolická konštanta k:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.k_var = tk.StringVar(value="k")  # Nastavené na 'k' ako v pôvodnom kóde
        ttk.Entry(left_frame, textvariable=self.k_var, width=15, state="disabled").grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(left_frame, text="(symbolická premenná)").grid(row=1, column=2, sticky=tk.W, pady=5)
        
        # omega funkcia - v pôvodnom kóde je to funkcia omega(r)
        ttk.Label(left_frame, text="Funkcia omega(r):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.omega_var = tk.StringVar(value="omega")  # Nastavíme na hodnotu ako v pôvodnom súbore
        ttk.Entry(left_frame, textvariable=self.omega_var, width=15, state="disabled").grid(row=2, column=1, sticky=tk.W, pady=5)
        ttk.Label(left_frame, text="(automaticky definovaná ako funkcia)").grid(row=2, column=2, sticky=tk.W, pady=5)
        
        # Informácia o LaTeX výstupe
        info_frame = ttk.LabelFrame(right_frame, text="Informácia o výstupe")
        info_frame.grid(row=0, column=0, pady=5, sticky=tk.NW)
        ttk.Label(info_frame, text="Výstup je generovaný v LaTeX formáte.") .grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(info_frame, text="Skopírujte kód a vložte ho do LaTeX editora.").grid(row=1, column=0, sticky=tk.W, pady=2)

        # Tlačidlá
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.run_button = ttk.Button(button_frame, text="Spustiť výpočet", command=self.run_calculation)
        self.run_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Zastaviť", command=self.stop_calculation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.clear_button = ttk.Button(button_frame, text="Vyčistiť výstup", command=self.clear_output)
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
        # Indikátor priebehu
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=5)
        
        self.status_label = ttk.Label(progress_frame, text="Pripravené")
        self.status_label.pack(pady=2)
        
        # Výstupný textový widget
        output_frame = ttk.LabelFrame(main_frame, text="Výsledky (LaTeX kód)", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, width=90, height=20, 
                                                  state=tk.DISABLED, font=self.code_font)
        self.output_text.pack(fill=tk.BOTH, expand=True)
                
        # Presmerovanie štandardného výstupu
        self.stdout_redirector = RedirectText(self.output_text)
            
    def update_status(self, text, progress=None):
        self.status_label.config(text=text)
        if progress is not None:
            self.progress_var.set(progress)
        self.root.update_idletasks()
    
    def clear_output(self):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state=tk.DISABLED)
        self.update_status("Výstup vyčistený", 0)
        
    def run_calculation(self):
        if self.running:
            return
            
        # Vymazať starý výstup
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state=tk.DISABLED)
        
        # Nastaviť stavy tlačidiel
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.DISABLED)
        
        # Spustiť výpočet vo vlákne
        self.running = True
        self.progress_var.set(0)
        self.calculation_thread = threading.Thread(target=self.perform_calculation)
        self.calculation_thread.daemon = True
        self.calculation_thread.start()
        
        # Pravidelná kontrola stavu výpočtu
        self.root.after(100, self.check_calculation_status)
        
    def check_calculation_status(self):
        if self.running and self.calculation_thread.is_alive():
            self.root.after(100, self.check_calculation_status)
        else:
            # Ak vlákno skončilo (normálne alebo chybou), zavoláme finish
            self.finish_calculation()
        
    def stop_calculation(self):
        if not self.running:
            return
            
        print("\n% Prijatý pokyn na zastavenie...\n")
        self.running = False
        self.update_status("Zastavovanie výpočtu...", self.progress_var.get())

    def print_separator(self):
        """Vytlačí jednoduchý oddeľovač pre LaTeX výstup"""
        print("\n%-----------------------------------------------------%\n")
    
    def print_section_header(self, text):
        """Vytlačí nadpis sekcie ako LaTeX komentár"""
        print(f"\n% ===== {text} ===== %\n")
    
    def pretty_print_tensor_latex(self, tensor, name, indices_list):
        """Vytlačí tenzor ako sériu LaTeX výrazov"""
        for indices in indices_list:
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený používateľom počas výpisu")
                
            if len(indices) == 2:
                i, j = indices
                print(f"% Počítam/Vypisujem {name}_{{{i}{j}}}")
                latex_expr = LatexOutputFormatter.format_tensor_component(name, [i, j], tensor[i, j])
                print(latex_expr)
            elif len(indices) == 1:
                 i = indices[0]
                 name_prefix = "G" if name == "G^" else "\\nabla_\\nu G^"
                 print(f"% Počítam/Vypisujem {name_prefix}^{{{i}}}")
                 latex_expr = LatexOutputFormatter.format_tensor_component(name_prefix, [i], tensor[i])
                 print(latex_expr)
    
    def perform_calculation(self):
        calculation_successful = False
        try:
            # Presmerovanie stdout na náš textový widget
            old_stdout = sys.stdout
            sys.stdout = self.stdout_redirector
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Definujem premenné a funkcie", 5))
            
            # Definícia súradníc a symbolických premenných
            t, r, theta, phi = sp.symbols('t r theta phi', real=True)
            k_const = sp.Symbol('k', real=True)
            omega = sp.Function('omega')(r)
            coords = [t, r, theta, phi]
            n = len(coords)
            
            self.print_section_header("Inicializácia výpočtu")
            print("% Symbolické premenné:")
            print(f"%   Súradnice: t, r, \\theta, \\phi")
            print(f"%   Konštanta: k")
            print(f"%   Funkcia: \\omega(r)")
            self.print_separator()
            
            # --- Metrický tenzor --- 
            self.root.after(0, lambda: self.update_status("Vytváram metrický tenzor", 10))
            self.print_section_header("Metrický tenzor g_{\\mu\\nu}")
            g = sp.Matrix([
                [
                    -sp.exp(-2 * k_const / r) + omega**2 * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2,
                    sp.diff(omega, r) * t * omega * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2,
                    0,
                    -omega * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2
                ],
                [
                    sp.diff(omega, r) * t * omega * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2,
                    -sp.exp(2 * k_const / r) * (1 + sp.diff(omega, r)**2 * t**2 * r**2 * sp.sin(theta)**2),
                    0,
                    -sp.diff(omega, r) * t * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2
                ],
                [0, 0, r**2 * sp.exp(2 * k_const / r), 0],
                [
                    -omega * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2,
                    -sp.diff(omega, r) * t * r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2,
                    0,
                    r**2 * sp.exp(2 * k_const / r) * sp.sin(theta)**2
                ]
            ])
            print(sp.latex(g))
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po definícii metriky")
            
            # --- Inverzná metrika --- 
            self.root.after(0, lambda: self.update_status("Počítam inverznú metriku", 20))
            self.print_section_header("Inverzná metrika g^{\\mu\\nu}")
            print("% Počítam inverznú metriku...\n")
            g_inv = sp.simplify(g.inv())
            print(sp.latex(g_inv))
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po inverznej metrike")

            # --- Christoffelove symboly --- 
            self.root.after(0, lambda: self.update_status("Počítam Christoffelove symboly", 30))
            self.print_section_header("Christoffelove symboly \\Gamma^{\\rho}_{\\mu\\nu}")
            print("% Počítam Christoffelove symboly...\n")
            Gamma = [[[sp.sympify(0) for _ in range(n)] for _ in range(n)] for _ in range(n)]
            for i in range(n):
                for j in range(n):
                    for l in range(n):
                        if not self.running: raise InterruptedError(f"Výpočet zastavený pri výpočte Gamma^{i}_{j}{l}")
                        print(f"% Počítam Gamma^{i}_{j}{l}...")
                        sum_val = sp.sympify(0)
                        for m in range(n):
                             term = g_inv[i, m] * (sp.diff(g[m, j], coords[l]) +
                                                   sp.diff(g[m, l], coords[j]) -
                                                   sp.diff(g[j, l], coords[m]))
                             sum_val += term
                        Gamma[i][j][l] = sp.simplify(sp.Rational(1, 2) * sum_val)
                progress = 30 + ((i + 1) / n * 15)
                self.root.after(0, lambda p=progress: self.update_status("Počítam Christoffelove symboly", p))
            print("% Výpočet Christoffelových symbolov dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Christoffelových symboloch")

            # --- Ricciho tenzor --- 
            self.root.after(0, lambda: self.update_status("Počítam Ricciho tenzor", 45))
            self.print_section_header("Ricciho tenzor R_{\\mu\\nu}")
            print("% Počítam Ricciho tenzor...\n")
            R = sp.Matrix.zeros(n, n)
            for mu in range(n):
                for nu in range(n):
                    if not self.running: raise InterruptedError(f"Výpočet zastavený pri výpočte R_{{{mu}}}{{{nu}}}")
                    print(f"% Počítam R_{{{mu}}}{{{nu}}}...")
                    term1 = sp.sympify(0)
                    for l_idx in range(n):
                        term1 += sp.diff(Gamma[l_idx][mu][nu], coords[l_idx])
                    term2 = sp.sympify(0)
                    for l_idx in range(n):
                        term2 += sp.diff(Gamma[l_idx][l_idx][nu], coords[mu])
                    term3 = sp.sympify(0)
                    for l_idx in range(n):
                        for r_idx in range(n):
                            term3 += Gamma[l_idx][mu][nu] * Gamma[r_idx][l_idx][r_idx]
                    term4 = sp.sympify(0)
                    for l_idx in range(n):
                        for r_idx in range(n):
                            term4 += Gamma[r_idx][mu][l_idx] * Gamma[l_idx][nu][r_idx]
                    R[mu, nu] = sp.simplify(term1 - term2 + term3 - term4)
                    print(f"% R_{{{mu}}}{{{nu}}} = {sp.latex(R[mu, nu])}\n")
                progress = 45 + ((mu + 1) / n * 15)
                self.root.after(0, lambda p=progress: self.update_status("Počítam Ricciho tenzor", p))
            print("% Výpočet Ricciho tenzora dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Ricciho tenzore")

            # --- Ricciho skalár --- 
            self.root.after(0, lambda: self.update_status("Počítam Ricciho skalár", 60))
            self.print_section_header("Ricciho skalár R")
            print("% Počítam Ricciho skalár...\n")
            R_scalar_expr = sp.sympify(0)
            for i in range(n):
                for j in range(n):
                    R_scalar_expr += g_inv[i, j] * R[i, j]
            R_scalar = sp.simplify(R_scalar_expr)
            print(sp.latex(R_scalar))
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Ricciho skalári")

            # --- Einsteinov tenzor --- 
            self.root.after(0, lambda: self.update_status("Počítam Einsteinov tenzor", 70))
            self.print_section_header("Einsteinov tenzor G_{\\mu\\nu}")
            print("% Počítam Einsteinov tenzor G_{\\mu\\nu} = R_{\\mu\\nu} - (1/2) * R * g_{\\mu\\nu}...\n")
            Einstein_T = sp.simplify(R - sp.Rational(1, 2) * R_scalar * g)
            indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(Einstein_T, "G", indices)
            print("% Výpočet Einsteinovho tenzora dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po Einsteinovom tenzore")

            # --- Zmiešané zložky Einsteinovho tenzora --- 
            self.root.after(0, lambda: self.update_status("Počítam zmiešané zložky G^{\\mu}_{\\nu}", 80))
            self.print_section_header("Zmiešané zložky Einsteinovho tenzora G^{\\mu}_{\\nu}")
            print("% Počítam zmiešané zložky G^{\\mu}_{\\nu} = g^{\\mu\\rho} * G_{\\rho\\nu}...\n")
            G_mixed = sp.simplify(g_inv * Einstein_T)
            mixed_indices = [(i, j) for i in range(n) for j in range(n)]
            self.pretty_print_tensor_latex(G_mixed, "G^", mixed_indices)
            print("% Výpočet zmiešaných zložiek dokončený.")
            self.print_separator()
            if not self.running: raise InterruptedError("Výpočet zastavený po zmiešaných zložkách")

            # --- Kovariantná divergencia --- 
            self.root.after(0, lambda: self.update_status("Počítam kovariantnú divergenciu", 90))
            self.print_section_header("Kovariantná divergencia \\nabla_\\nu G^{\\mu\\nu}")
            print("% Počítam kovariantnú divergenciu \\nabla_\\nu G^{\\mu\\nu}...\n")
            div_G = sp.Matrix.zeros(n, 1)
            for mu in range(n):
                if not self.running: raise InterruptedError(f"Výpočet zastavený pri výpočte divergencie pre \\mu={{{mu}}}")
                print(f"% Počítam zložku divergencie pre \\mu={{{mu}}}...")
                expr = sp.sympify(0)
                term_diff = sp.sympify(0)
                for nu in range(n):
                    print(f"%   Derivujem G^{{{mu}}}_{{{nu}}} podľa súradnice {{{coords[nu].name}}}...")
                    term_diff += sp.diff(G_mixed[mu, nu], coords[nu])
                print(f"%   Výsledok derivácie pre \\mu={{{mu}}}: {sp.latex(term_diff)}")
                expr += term_diff
                
                term_gamma1 = sp.sympify(0)
                term_gamma2 = sp.sympify(0)
                for nu in range(n):
                     for l in range(n):
                         print(f"%   Pridávam člen Gamma^{{{mu}}}_{{{l}}}{{{nu}}} * G^{{{l}}}_{{{nu}}}...")
                         term_gamma1 += Gamma[mu][l][nu] * G_mixed[l, nu]
                         print(f"%   Pridávam člen Gamma^{{{l}}}_{{{l}}}{{{nu}}} * G^{{{mu}}}_{{{nu}}}...")
                         term_gamma2 += Gamma[l][l][nu] * G_mixed[mu, nu] 
                
                print(f"%   Výsledok 1. Gamma člena pre \\mu={{{mu}}}: {sp.latex(term_gamma1)}")
                print(f"%   Výsledok 2. Gamma člena pre \\mu={{{mu}}}: {sp.latex(term_gamma2)}")
                expr += term_gamma1 + term_gamma2

                print(f"%   Výsledný výraz pre divergenciu (pred simplify) pre \\mu={{{mu}}}: {sp.latex(expr)}")
                print(f"%   Zjednodušujem výraz pre divergenciu pre \\mu={{{mu}}}...")
                div_G[mu] = sp.simplify(expr)
                print(f"%   Výsledok divergencie pre \\mu={{{mu}}}: {sp.latex(div_G[mu])}\n")
                
                progress = 90 + ((mu + 1) / n * 10)
                self.root.after(0, lambda p=progress: self.update_status("Počítam kovariantnú divergenciu", p))
            
            self.print_section_header("Výsledok - Kovariantná divergencia \\nabla_\\nu G^{\\mu\\nu}")
            div_indices = [(i,) for i in range(n)]
            self.pretty_print_tensor_latex(div_G, "\\nabla_\\nu G^", div_indices)
            print("% Výpočet kovariantnej divergencie dokončený.")
            self.print_separator()
            
            self.root.after(0, lambda: self.update_status("Výpočet dokončený", 100))
            self.print_section_header("Výpočet úspešne dokončený")
            calculation_successful = True
            
        except InterruptedError as e:
            print(f"\n% !!! VÝPOČET PRERUŠENÝ POUŽÍVATEĽOM !!!")
            print(f"% Dôvod: {str(e)}")
            self.root.after(0, lambda: self.update_status(f"Výpočet zastavený: {str(e)}", self.progress_var.get()))
        except Exception as e:
            print(f"\n% !!! CHYBA PRI VÝPOČTE !!!")
            print(f"% Chyba: {str(e)}")
            import traceback
            print("% Traceback:")
            tb_lines = traceback.format_exc().splitlines()
            for line in tb_lines:
                print(f"% {line}")
            self.root.after(0, lambda: self.update_status(f"Chyba: {str(e)}", self.progress_var.get()))
        finally:
            # Obnova štandardného výstupu
            sys.stdout = old_stdout
            if calculation_successful:
                 self.root.after(0, lambda: self.update_status("Výpočet dokončený", 100))
            
    def finish_calculation(self):
        self.running = False
        self.run_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL)
        
if __name__ == "__main__":
    root = tk.Tk()
    app = EinsteinCalculatorApp(root)
    root.mainloop() 
