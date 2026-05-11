from trytond.pool import Pool

from . import procurement


def register():
    Pool.register(
        procurement.MedicalPurchaseAudit,
        procurement.MedicalPurchaseProcurementRound,
        procurement.MedicalPurchaseProcurementProposal,
        procurement.UploadProcurementResponseStart,
        procurement.DownloadProcurementResponseResult,
        procurement.StartProcurementRoundStart,
        procurement.StartProcurementRoundParty,
        procurement.SelectProcurementWinnerStart,
        procurement.GenerateProcurementPurchaseStart,
        module='z_001_medical_purchase_procurement', type_='model')
    Pool.register(
        procurement.UploadProcurementResponseWizard,
        procurement.DownloadProcurementResponseWizard,
        procurement.StartProcurementRoundWizard,
        procurement.SelectProcurementWinnerWizard,
        procurement.GenerateProcurementPurchaseWizard,
        module='z_001_medical_purchase_procurement', type_='wizard')
    Pool.register(
        procurement.MedicalPurchaseProcurementProposalBudgetRequestReport,
        module='z_001_medical_purchase_procurement', type_='report')
