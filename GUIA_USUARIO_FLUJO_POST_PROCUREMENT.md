# Guia de Usuario: Flujo Post-Procurement

## Objetivo
Esta guia explica que debe hacer cada perfil en el sistema desde que `Medical Procurement` genera la compra hasta que los medicamentos quedan:

- recibidos correctamente,
- disponibles en stock,
- y listos para una futura entrega manual asistida a pacientes.

El objetivo de este documento es operativo. Indica donde entrar, que revisar, que tocar y que deberia pasar en cada etapa.

## Alcance de esta guia
Esta guia cubre el flujo desde:

- ronda de procurement con ganador seleccionado,
- compra generada,
- compra confirmada o procesada,
- recepcion del proveedor,
- ingreso real al stock,
- preparacion futura de entrega por paquete.

Esta guia no describe implementacion tecnica ni cambios de codigo.

## Idea clave del flujo
Despues de que `medical procurement` genera la compra, el flujo deja de estar principalmente en el modulo custom y pasa a usar funciones nativas de compras y stock de Tryton.

El recorrido esperado es:

1. `Compra generada`
2. `Compra procesada`
3. `Recepcion del proveedor`
4. `Ingreso real al stock`
5. `Apertura futura del paquete auditado`
6. `Entrega manual asistida al paciente`

## Aclaraciones importantes

### Compra procesada no es lo mismo que stock recibido
Que la compra exista y este confirmada o procesada no significa que el medicamento ya este disponible para entregar.

El stock queda realmente disponible recien cuando se procesa la recepcion del proveedor.

### Que es `stock.shipment.in`
Es el documento nativo de Tryton para registrar la recepcion del proveedor.

En ese documento se controla:

- que productos llegaron,
- que cantidad llego,
- si la recepcion fue total o parcial,
- lote,
- vencimiento,
- y diferencias con lo comprado.

### Que es `stock.move`
Es el movimiento de stock en si mismo.

No suele trabajarse como una pantalla aislada en este flujo. Normalmente aparece dentro de documentos nativos mas grandes, por ejemplo:

- la compra,
- la recepcion del proveedor,
- una salida de stock,
- una transferencia interna.

### Como se relacionan compra, recepcion, stock y paquete
La idea funcional es la siguiente:

- `Medical Procurement` genera la compra.
- La compra habilita el flujo logistico nativo.
- La recepcion del proveedor registra lo que efectivamente entro.
- Esa recepcion impacta en el stock real del deposito.
- El paquete auditado sigue siendo el contexto clinico que permite saber a que recetas y pacientes corresponde ese abastecimiento.

## Punto de partida
Esta guia parte de una ronda de procurement que ya:

- tiene propuesta ganadora,
- genero una `Compra`,
- y dejo la compra confirmada o lista para continuar el flujo operativo.

En este punto, el usuario debe poder identificar:

- la ronda,
- la compra generada,
- y el documento o paquete de origen.

## Flujo por perfil

## Compras

### Paso 1: abrir la compra generada

#### Donde entrar
La compra se puede encontrar por dos caminos:

1. Desde la ronda de procurement:
   - abrir la ronda,
   - ubicar el campo `Compra Generada`.

2. Desde el menu nativo de compras:
   - `Purchase -> Purchases`

#### Que revisar
Antes de continuar, revisar:

- proveedor,
- deposito,
- lineas de productos,
- cantidades,
- referencia al origen,
- descripcion general de la compra.

#### Que tocar
Si la compra fue generada correctamente desde procurement, en principio no deberia rehacerse manualmente.

La accion principal esperada en esta etapa es continuar el flujo normal de compra.

### Paso 2: procesar la compra

#### Donde entrar
Dentro de la propia `Compra`.

#### Que hace este paso
Procesar la compra:

- deja la compra dentro del flujo operativo de Tryton,
- activa o prepara los movimientos relacionados,
- habilita el circuito de recepcion del proveedor.

#### Que tocar
Segun la configuracion visible en la instancia, el usuario debera usar la accion estandar de la compra para continuar su procesamiento.

#### Que deberia pasar
Despues de este paso:

- la compra debe quedar lista para ser recibida,
- y debe poder encontrarse su recepcion vinculada.

#### Importante
Este paso no mete todavia el medicamento al stock real.

## Deposito / Logistica / Farmacia Logistica

### Paso 3: encontrar la recepcion del proveedor

#### Donde entrar
Hay dos caminos habituales:

1. Desde la compra:
   - abrir la compra,
   - entrar al enlace o relacion de `Shipments`.

2. Desde el menu nativo de stock:
   - `Inventory & Stock -> Supplier Shipments`

#### Que documento usar
El documento esperado es la recepcion de proveedor:

- `stock.shipment.in`

### Paso 4: registrar la recepcion

#### Que revisar
En la recepcion el usuario debe controlar:

- productos recibidos,
- cantidades recibidas,
- si la entrega fue total o parcial,
- diferencias respecto de la compra,
- lote,
- fecha de vencimiento,
- estado general de la recepcion.

#### Que tocar
Dentro de la `Supplier Shipment`, el usuario debe:

1. revisar las lineas esperadas,
2. ajustar cantidades si la recepcion fue parcial,
3. cargar lote y vencimiento cuando corresponda,
4. continuar el flujo normal de recepcion de Tryton.

#### Que deberia pasar
Al procesar correctamente la recepcion:

- el sistema registra que el proveedor entrego la mercaderia,
- el stock entra al deposito de destino,
- el medicamento queda disponible para el siguiente uso operativo.

### Paso 5: manejar recepcion parcial o con diferencias

#### Cuando aplica
Este paso aplica si:

- llego menos cantidad,
- llego una parte,
- hubo diferencia entre compra y entrega,
- un lote no sirve,
- o se necesita devolver parte de lo recibido.

#### Que hacer
El usuario debe reflejar lo ocurrido en la recepcion nativa, sin forzar que el sistema marque como recibido algo que no llego correctamente.

#### Que deberia pasar
El stock solo debe quedar disponible por la cantidad efectivamente recibida y aceptada.

## Farmacia Asistencial

### Paso 6: verificar que el stock ya esta disponible

#### Donde entrar
Esto puede verificarse desde:

- la propia recepcion,
- consultas de stock,
- movimientos de stock,
- o vistas de disponibilidad por producto y deposito.

#### Que revisar
Revisar:

- producto,
- deposito,
- cantidad disponible,
- lote,
- vencimiento.

#### Que deberia pasar
Si la recepcion ya fue procesada correctamente, el medicamento debe figurar como disponible en el deposito correspondiente.

### Paso 7: trabajar desde el paquete auditado

#### Donde deberia estar
La entrega al paciente no deberia partir desde la compra sino desde el `Paquete Auditado`.

El paquete auditado es el contexto clinico porque agrupa las recetas y lineas de medicamentos que originaron la necesidad de compra.

#### Por que no partir desde la compra
La compra sirve bien como documento logistico, pero no es la mejor pantalla para operar entregas a pacientes.

Desde el paquete se conserva mejor el contexto de:

- receta,
- paciente,
- medicamento,
- y pendientes de entrega.

### Paso 8: futura vista de entrega por paquete

#### Estado actual
Esta pantalla es futura. No se documenta como algo ya implementado.

#### Que deberia mostrar
La futura vista `Entrega por Paquete` deberia mostrar, como minimo:

- paquete auditado,
- recetas incluidas,
- pacientes,
- medicamentos,
- cantidades pendientes,
- stock disponible,
- lotes disponibles,
- vencimientos disponibles.

#### Para que serviria
Serviria para que farmacia pueda decidir manualmente:

- a que paciente entregar primero,
- que cantidad entregar,
- que lote utilizar,
- y que lineas siguen pendientes.

### Paso 9: futura entrega manual asistida

#### Estado actual
Este flujo es futuro. No debe interpretarse como funcionalidad ya disponible.

#### Como deberia ser
Desde la vista del paquete, el operador deberia:

1. abrir una linea pendiente,
2. verificar paciente y receta,
3. elegir la cantidad a entregar,
4. seleccionar el lote disponible,
5. confirmar la entrega.

#### Que deberia pasar
En un flujo futuro completo, el sistema deberia:

- registrar la entrega clinica,
- descontar stock con el movimiento nativo correspondiente,
- y dejar actualizada la cantidad pendiente.

## Resumen rapido de navegacion

### Usuario de Compras
1. Abrir la ronda de procurement
2. Entrar a `Compra Generada`
3. Revisar la compra
4. Procesar la compra

### Usuario de Deposito o Logistica
1. Abrir la compra o entrar a `Inventory & Stock -> Supplier Shipments`
2. Encontrar la recepcion vinculada
3. Registrar recepcion total o parcial
4. Cargar lote y vencimiento
5. Procesar la recepcion

### Usuario de Farmacia
1. Verificar que el stock ya este disponible
2. Abrir el paquete auditado
3. Usar en el futuro la vista `Entrega por Paquete`
4. Registrar entregas manuales asistidas por receta y paciente

## Que deberia validar el usuario al final del flujo
Al finalizar esta parte del circuito, deberia poder confirmarse que:

- la compra fue generada desde procurement,
- la compra fue procesada,
- la recepcion del proveedor fue registrada,
- el stock entro realmente al deposito,
- y el paquete auditado sigue siendo el punto de referencia clinico para futuras entregas.

## Conclusion
El flujo correcto desde procurement en adelante se entiende mejor asi:

- `Medical Procurement` compra,
- `Tryton nativo` recibe e ingresa a stock,
- y el `Paquete Auditado` conserva el contexto clinico para la futura entrega al paciente.

Ese orden evita confundir:

- compra confirmada,
- recepcion efectiva,
- y disponibilidad real para entregar.
