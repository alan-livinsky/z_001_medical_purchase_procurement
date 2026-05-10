# Plan Maestro: Nuevo modulo `z_001_medical_purchase_procurement`

## Resumen

Crear un modulo nuevo, separado de `z_001_medical_purchases_audit`, para continuar el flujo desde un documento medico de compras en estado `accepted` hasta una compra Tryton confirmada.

Este modulo nuevo sera responsable de:
- gestionar la comparacion de proveedores
- permitir atajos por `wizards` y `form_action`
- elegir una oferta ganadora
- generar y confirmar la `purchase.purchase`

El flujo actual de `z_001_medical_purchases_audit` no se expande funcionalmente mas alla de `accepted`; solo se usara como origen del nuevo proceso.

Primera tarea de implementacion:
- crear la carpeta del modulo `z_001_medical_purchase_procurement`
- guardar una copia de este plan dentro del modulo en formato Markdown, preferentemente como `PLAN.md`

## Flujo funcional objetivo

1. `z_001_prescription_audit` genera el paquete.
2. `z_001_medical_purchases_audit` genera, firma y obtiene un documento `accepted`.
3. Desde ese `accepted`, un wizard del nuevo modulo inicia una ronda de procurement.
4. El wizard solicita multiples proveedores y crea una estructura comparadora interna.
5. Compras carga o ajusta precios, cantidades y observaciones por proveedor.
6. Un wizard de seleccion marca una propuesta ganadora.
7. Otro wizard genera una `purchase.purchase` desde esa propuesta ganadora.
8. El mismo flujo valida precondiciones y ejecuta `quote` + `confirm`.
9. El flujo custom termina cuando la compra queda `confirmed`.

## Modulos intervinientes

### Modulos custom
- `z_001_prescription_audit`
  - origen del paquete
- `z_001_medical_purchases_audit`
  - origen del documento aceptado
- `z_001_medical_purchase_procurement`
  - comparacion de proveedores
  - seleccion de oferta
  - creacion y confirmacion de compra
  - accesos, menus, vistas y wizards

### Modulos estandar Tryton
- `purchase`
- `party`
- `product`
- `company`

### Modulos estandar posteriores, fuera de este corte
- `stock`
- `account_invoice`
- `account`

## Alcance exacto del nuevo modulo

El nuevo modulo si debe incluir:
- punto de entrada desde `gnuhealth.medical.purchase.audit`
- modelos internos para ronda comparativa, propuestas y lineas
- wizards para iniciar ronda, seleccionar ganador y generar compra
- trazabilidad entre auditoria aceptada, ronda, propuesta ganadora y compra
- permisos y menus propios

El nuevo modulo no debe incluir en esta version:
- recepcion de stock custom
- factura de proveedor custom
- asientos o contabilizacion custom
- pago a proveedor
- automatizacion de multiples ordenes reales a proveedores no ganadores

## Modelo funcional a agregar

### 1. Ronda de procurement
Modelo cabecera enlazado a un `gnuhealth.medical.purchase.audit` en estado `accepted`.

Campos minimos:
- nombre
- documento origen
- estado interno
- fecha
- usuario creador
- observaciones
- propuesta ganadora
- compra generada
- indicador de cierre

Estados propuestos:
- `draft`
- `in_comparison`
- `winner_selected`
- `purchase_created`
- `done`
- `cancelled`

Reglas:
- una sola ronda activa por documento `accepted`
- no se modifica el documento fuente
- cancelar ronda permite iniciar otra nueva

### 2. Propuesta de proveedor
Una propuesta por proveedor dentro de la ronda.

Campos minimos:
- ronda
- proveedor
- estado
- total
- observaciones
- seleccionada como ganadora
- compra vinculada si corresponde

Regla:
- proveedor unico por ronda

### 3. Lineas de propuesta
Lineas copiadas desde el documento aceptado.

Campos minimos:
- propuesta
- medicamento/producto
- cantidad
- precio unitario
- subtotal
- observaciones

Reglas:
- cantidad por defecto = `purchase_quantity` aprobada
- no se admiten cantidades negativas
- la propuesta ganadora debe tener precios completos

## Interfaz y atajos

### Wizard 1: iniciar ronda
`form_action` sobre `gnuhealth.medical.purchase.audit`

Disponible si:
- estado = `accepted`
- no existe ronda activa
- usuario del grupo de compras

Funcion:
- mostrar resumen del documento
- seleccionar multiples proveedores
- crear ronda, propuestas y lineas

### Wizard 2: seleccionar ganador
`form_action` sobre la ronda de procurement

Funcion:
- mostrar comparativo resumido
- obligar a elegir una sola propuesta
- bloquear si faltan precios o datos obligatorios

### Wizard 3: generar compra
`form_action` sobre ronda en `winner_selected`

Funcion:
- validar proveedor, lineas y datos minimos de compra
- crear `purchase.purchase` en `draft`
- crear `purchase.line`
- ejecutar `quote`
- ejecutar `confirm`
- guardar vinculo con la ronda

### Navegacion
Agregar:
- acceso desde el documento `accepted` a sus rondas
- acceso desde la ronda a la compra generada
- menu propio bajo Compras Medicas para consultar rondas

## Reglas de negocio cerradas

- Solo documentos `accepted` pueden iniciar procurement.
- Solo Compras puede operar el flujo nuevo.
- Auditoria medica puede consultar, no editar.
- Solo una propuesta ganadora por ronda.
- Solo una compra real por ronda.
- Si falla la confirmacion, debe quedar trazabilidad clara del error en espanol.
- La compra no se regenera automaticamente si ya existe una para la ronda.
- Si hace falta rehacer el proceso, se cancela la ronda y se inicia otra.

## Conversion a `purchase.purchase`

Mapeo minimo:
- proveedor ganador -> `purchase.party`
- lineas ganadoras -> `purchase.line`
- cantidad final -> cantidad de la propuesta ganadora
- precio unitario -> precio cotizado ganador
- descripcion/origen -> referencia a documento medico y ronda
- warehouse -> default del sistema o dato resuelto por wizard si falta

Politica:
- la comparacion vive solo en el modulo custom
- solo la propuesta ganadora se convierte en compra Tryton
- los proveedores no ganadores no generan `purchase.purchase`

## Dependencias y estructura del modulo

`tryton.cfg` del nuevo modulo debe depender como minimo de:
- `ir`
- `health`
- `purchase`
- `z_001_medical_purchases_audit`

Estructura esperada:
- modelos principales del comparador
- wizards de inicio, seleccion y generacion de compra
- XML de vistas, acciones, keywords, menus y permisos
- archivo `PLAN.md` con este plan como referencia de trabajo

## Configuracion minima requerida

Para que esta version funcione hasta compra confirmada, se requiere:
- compania activa
- proveedores validos
- productos/medicamentos utilizables en compra
- UoM consistente
- warehouse resoluble para la compra
- configuracion estandar suficiente para que `purchase.quote` y `purchase.confirm` no fallen

No se exigira contabilidad completa como prerrequisito formal del modulo, pero si la instalacion local la vuelve necesaria para confirmar compras, el wizard debe detectar el faltante y bloquear con mensaje claro en espanol.

## Casos de prueba

1. Iniciar ronda desde documento `accepted`.
2. Bloquear inicio desde `draft`, `signed_by_purchases` o `rejected`.
3. Crear ronda con multiples proveedores.
4. Bloquear segunda ronda activa para el mismo documento.
5. Cargar precios por proveedor y verificar totales.
6. Bloquear seleccion de ganador con propuesta incompleta.
7. Seleccionar una unica propuesta ganadora.
8. Generar compra desde la propuesta elegida.
9. Verificar compra en `confirmed`.
10. Bloquear segunda compra para la misma ronda.
11. Verificar trazabilidad:
   - documento aceptado -> ronda
   - ronda -> propuesta ganadora
   - ronda -> compra generada
12. Verificar permisos y mensajes en espanol.
13. Verificar que el flujo estandar de Tryton pueda continuar luego con stock/factura sin custom adicional.

## Supuestos y decisiones tomadas

- El modulo nuevo se llamara `z_001_medical_purchase_procurement`.
- La interfaz principal sera por `wizards guiados`.
- La comparacion de multiples proveedores se resolvera con un comparador interno previo.
- El objetivo de esta primera version termina en compra `confirmed`.
- `stock`, `account_invoice` y `account` quedan fuera del flujo custom inicial.
- La primera accion de implementacion sera crear la carpeta del modulo y guardar este plan dentro como `PLAN.md`.
