"""Proceso COM aislado. No expone detalles de excepciones del perfil de Office."""
import json
from pathlib import Path
import sys


def excel(path, evidence):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = book = None
    try:
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        app.AutomationSecurity = 3
        book = app.Workbooks.Open(str(path.resolve()), UpdateLinks=0, ReadOnly=False)
        if book.ReadOnly:
            raise RuntimeError("READ_ONLY")
        before = book.Worksheets("Ejecuciones").Range("F2").Value
        book.Worksheets("Ejecuciones").Range("F2").Value = "COM_VERIFICADO"
        app.CalculateFullRebuild()
        total = book.Worksheets("Resumen").Range("B8").Value
        version = app.Version
        book.Save()
        book.Close(False)
        book = app.Workbooks.Open(str(path.resolve()), UpdateLinks=0, ReadOnly=True)
        after = book.Worksheets("Ejecuciones").Range("F2").Value
        if after != "COM_VERIFICADO":
            raise RuntimeError("SAVE_NOT_VERIFIED")
        evidence.write_text(json.dumps({"status": "VERIFICADO", "version": version,
            "before": before, "after": after, "formula_total": total, "reopened": True}), encoding="utf-8")
    finally:
        if book is not None:
            book.Close(False)
        if app is not None:
            app.Quit()
        pythoncom.CoUninitialize()


def outlook(payload_path, evidence):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
        app = win32com.client.Dispatch("Outlook.Application")
        session = app.GetNamespace("MAPI")
        account = next((a for a in session.Accounts if str(a.SmtpAddress).lower() == data["mailbox"].lower()), None)
        if account is None:
            raise RuntimeError("ACCOUNT_MISMATCH")
        item = app.CreateItem(0)
        item.SendUsingAccount = account
        item.To = data["recipient"]
        item.Subject = data["subject"]
        item.HTMLBody = data["html"]
        item.Attachments.Add(str(Path(data["attachment"]).resolve()))
        if not item.Recipients.ResolveAll():
            raise RuntimeError("RECIPIENT_UNRESOLVED")
        item.Send()
        evidence.write_text(json.dumps({"status": "ACEPTADO", "version": app.Version,
                                       "delivery_confirmed": False}), encoding="utf-8")
        # No cerrar Outlook: puede pertenecer a la sesión interactiva del usuario.
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    try:
        {"excel": excel, "outlook": outlook}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    except Exception:
        sys.exit(2)
