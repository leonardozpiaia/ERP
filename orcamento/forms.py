import datetime

from django import forms

from obras.models import Obra

TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB


class ImportarPlanilhaForm(forms.Form):
    obra = forms.ModelChoiceField(label="Obra", queryset=Obra.objects.all())
    descricao = forms.CharField(label="Descrição do orçamento", max_length=200, initial="Orçamento importado")
    data_base = forms.DateField(label="Data-base dos preços", initial=datetime.date.today)
    bdi_percentual = forms.DecimalField(
        label="BDI (%)", max_digits=6, decimal_places=2, min_value=0, initial=0,
        help_text="Use os preços unitários SEM BDI na planilha; o BDI é aplicado sobre o total.",
    )
    arquivo = forms.FileField(label="Planilha (.xlsx)")

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError(
                "Envie um arquivo .xlsx. No Excel, use Arquivo → Salvar como → Pasta de Trabalho do Excel (.xlsx)."
            )
        if arquivo.size > TAMANHO_MAXIMO:
            raise forms.ValidationError("Arquivo maior que 10 MB.")
        return arquivo
