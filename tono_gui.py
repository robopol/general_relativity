import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
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
                print(f"Chyba v update_worker: {e}")
                time.sleep(0.1)

    def update_text(self, string):
        try:
            self.output.config(state=tk.NORMAL)
            self.output.insert(tk.END, string)
            self.output.see(tk.END)
            self.output.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Chyba pri aktualizácii textu: {e}")
    
    def flush(self):
        pass

    def stop(self):
        self.updating = False

class EinsteinCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Kalkulátor Einsteinových tenzorov")
        self.root.geometry("1000x700")
        
        self.running = False
        self.calculation_thread = None
        self.progress_var = tk.DoubleVar(value=0)
        
        self.create_widgets()
        
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
        ttk.Entry(left_frame, textvariable=self.k_var, width=15).grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(left_frame, text="(symbolická premenná)").grid(row=1, column=2, sticky=tk.W, pady=5)
        
        # omega funkcia - v pôvodnom kóde je to funkcia omega(r)
        ttk.Label(left_frame, text="Funkcia omega(r):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.omega_var = tk.StringVar(value="omega")  # Nastavíme na hodnotu ako v pôvodnom súbore
        ttk.Entry(left_frame, textvariable=self.omega_var, width=15, state="disabled").grid(row=2, column=1, sticky=tk.W, pady=5)
        ttk.Label(left_frame, text="(automaticky definovaná ako funkcia)").grid(row=2, column=2, sticky=tk.W, pady=5)
        
        # Nastavenia výstupu
        output_settings_frame = ttk.LabelFrame(right_frame, text="Nastavenia výstupu")
        output_settings_frame.grid(row=0, column=0, pady=5, sticky=tk.NW)
        
        # Checkbox pre Unicode výstup
        self.use_unicode = tk.BooleanVar(value=True)
        ttk.Checkbutton(output_settings_frame, text="Použiť Unicode formátovanie", 
                        variable=self.use_unicode).grid(row=0, column=0, sticky=tk.W, pady=2)
        
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
        output_frame = ttk.LabelFrame(main_frame, text="Výsledky", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, width=90, height=20, state=tk.DISABLED)
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
            self.finish_calculation()
        
    def stop_calculation(self):
        if not self.running:
            return
            
        self.running = False
        if self.calculation_thread and self.calculation_thread.is_alive():
            # Čakáme na dokončenie vlákna
            self.output_text.config(state=tk.NORMAL)
            self.output_text.insert(tk.END, "\nVýpočet sa zastavuje...\n")
            self.output_text.config(state=tk.DISABLED)
            self.update_status("Zastavovanie výpočtu...", 0)
        
    def perform_calculation(self):
        try:
            # Presmerovanie stdout na náš textový widget
            old_stdout = sys.stdout
            sys.stdout = self.stdout_redirector
            
            # Inicializácia SymPy - presne ako v pôvodnom súbore
            sp.init_printing(use_unicode=self.use_unicode.get())
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Definujem premenné a funkcie", 5))
            
            # Definícia súradníc a symbolických premenných - presne ako v pôvodnom súbore
            t, r, theta, phi = sp.symbols('t r theta phi', real=True)
            k_const = sp.Symbol('k', real=True)  # Presne ako v pôvodnom súbore
            omega = sp.Function('omega')(r)      # Presne ako v pôvodnom súbore
            
            # Zoznam súradníc
            coords = [t, r, theta, phi]
            
            print("Inicializujem výpočet s preddefinovanými symbolickými premennými:")
            print("Súradnice: t, r, theta, phi")
            print("Konštanta: k")
            print("Funkcia: omega(r)")
            print("-" * 40)
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Vytváram metrický tenzor", 10))
            
            # Definícia metrického tenzora podľa zadania - presne ako v pôvodnom súbore
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
            
            print("Metrický tenzor g_μν:")
            sp.pprint(g)
            print("-" * 40)
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam inverznú metriku", 20))
            
            # Inverzná metrika - presne ako v pôvodnom súbore
            print("Počítam inverznú metriku...")
            g_inv = sp.simplify(g.inv())  # Presne ako v pôvodnom súbore
            
            print("Inverzná metrika g^μν:")
            sp.pprint(g_inv)
            print("-" * 40)
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
                
            # Dimenzia
            n = g.shape[0]
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam Christoffelové symboly", 30))
            
            # Výpočet Christoffelových symbolov - presne ako v pôvodnom súbore
            print("Počítam Christoffelové symboly...")
            Gamma = [[[0 for _ in range(n)] for _ in range(n)] for _ in range(n)]
            
            for i in range(n):
                for j in range(n):
                    for l in range(n):
                        Gamma[i][j][l] = sp.Rational(1, 2) * sum(
                            g_inv[i, m] * (sp.diff(g[m, j], coords[l]) +
                                          sp.diff(g[m, l], coords[j]) -
                                          sp.diff(g[j, l], coords[m]))
                            for m in range(n)
                        )
                        # Kontrolujeme či výpočet nebol zastavený
                        if not self.running:
                            raise InterruptedError("Výpočet bol zastavený")
                
                # Aktualizujeme indikátor priebehu
                progress = 30 + (i / n * 15)
                self.root.after(0, lambda p=progress: self.update_status("Počítam Christoffelové symboly", p))
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam Ricciho tenzor", 45))
            
            # Výpočet Ricciho tenzora - presne ako v pôvodnom súbore
            print("Počítam Ricciho tenzor...")
            R = sp.Matrix.zeros(n, n)
            
            for mu in range(n):
                for nu in range(n):
                    term1 = sum(sp.diff(Gamma[l][mu][nu], coords[l]) for l in range(n))
                    term2 = sum(sp.diff(Gamma[mu][l][nu], coords[l]) for l in range(n))
                    term3 = sum(sum(Gamma[l][mu][nu] * Gamma[r][l][r] for r in range(n)) for l in range(n))
                    term4 = sum(sum(Gamma[mu][l][r] * Gamma[r][nu][l] for r in range(n)) for l in range(n))
                    R[mu, nu] = sp.simplify(term1 - term2 + term3 - term4)  # Presne ako v pôvodnom súbore
                    
                    # Kontrolujeme či výpočet nebol zastavený
                    if not self.running:
                        raise InterruptedError("Výpočet bol zastavený")
                
                # Aktualizujeme indikátor priebehu
                progress = 45 + (mu / n * 15)
                self.root.after(0, lambda p=progress: self.update_status("Počítam Ricciho tenzor", p))
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam Ricciho skalár", 60))
            
            # Ricciho skalár - presne ako v pôvodnom súbore
            print("Počítam Ricciho skalár...")
            R_scalar = sp.simplify(sum(g_inv[i, j] * R[i, j] for i in range(n) for j in range(n)))  # Presne ako v pôvodnom súbore
            
            print("Ricciho skalár R:")
            sp.pprint(R_scalar)
            print("-" * 40)
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam Einsteinov tenzor", 70))
            
            # Einsteinov tenzor G_{μν} - presne ako v pôvodnom súbore
            print("Počítam Einsteinov tenzor...")
            Einstein_T = sp.simplify(R - sp.Rational(1, 2) * R_scalar * g)  # Presne ako v pôvodnom súbore
            
            print("\n--- Einsteinov tenzor G_{μν} ---")
            for i in range(n):
                for j in range(n):
                    print(f"G_{{{i}{j}}} =")
                    sp.pprint(Einstein_T[i, j], use_unicode=False)
                    print()
                    
                    # Kontrolujeme či výpočet nebol zastavený
                    if not self.running:
                        raise InterruptedError("Výpočet bol zastavený")
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam zmiešané zložky Einsteinovho tenzora", 80))
            
            # Zmiešané zložky Einsteinovho tenzora G^μ_ν - presne ako v pôvodnom súbore
            print("Počítam zmiešané zložky Einsteinovho tenzora...")
            G_mixed = sp.simplify(g_inv * Einstein_T)  # Presne ako v pôvodnom súbore
            
            print("\n--- Zmiešané zložky Einsteinovho tenzora G^μ_ν ---")
            for i in range(n):
                for j in range(n):
                    print(f"G^{{{i}}}_{{{j}}} =")
                    sp.pprint(G_mixed[i, j], use_unicode=False)
                    print("-" * 40)
                    
                    # Kontrolujeme či výpočet nebol zastavený
                    if not self.running:
                        raise InterruptedError("Výpočet bol zastavený")
            
            if not self.running:
                raise InterruptedError("Výpočet bol zastavený")
            
            # Aktualizácia stavu
            self.root.after(0, lambda: self.update_status("Počítam kovariantnú divergenciu", 90))
            
            # Kovariantná divergencia ∇_ν G^μν - presne ako v pôvodnom súbore
            print("Počítam kovariantnú divergenciu Einsteinovho tenzora...")
            div_G = sp.Matrix.zeros(n, 1)
            for mu in range(n):
                expr = 0
                for nu in range(n):
                    expr += sp.diff(G_mixed[mu, nu], coords[nu])
                    for l in range(n):
                        expr += G_mixed[l, nu] * Gamma[mu][nu][l]
                div_G[mu] = sp.simplify(expr)  # Presne ako v pôvodnom súbore
                
                # Aktualizujeme indikátor priebehu
                progress = 90 + (mu / n * 10)
                self.root.after(0, lambda p=progress: self.update_status("Počítam kovariantnú divergenciu", p))
                
                # Kontrolujeme či výpočet nebol zastavený
                if not self.running:
                    raise InterruptedError("Výpočet bol zastavený")
            
            print("\n--- Kovariantná divergencia zmiešaného Einsteinovho tenzora ∇_ν G^μν ---")
            for i in range(n):
                print(f"∇_ν G^{{{i}ν}} =")
                sp.pprint(div_G[i], use_unicode=False)
                print("=" * 40)
            
            self.root.after(0, lambda: self.update_status("Výpočet dokončený", 100))
            print("\nVýpočet dokončený!")
            
        except InterruptedError as e:
            print(f"\n{str(e)}!")
            self.root.after(0, lambda: self.update_status("Výpočet zastavený", 0))
        except Exception as e:
            print(f"\nChyba pri výpočte: {str(e)}")
            self.root.after(0, lambda: self.update_status(f"Chyba: {str(e)}", 0))
        finally:
            # Obnova štandardného výstupu
            sys.stdout = old_stdout
            
    def finish_calculation(self):
        self.running = False
        self.run_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL)
        
if __name__ == "__main__":
    root = tk.Tk()
    app = EinsteinCalculatorApp(root)
    root.mainloop() 