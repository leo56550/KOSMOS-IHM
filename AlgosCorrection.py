#! usr/bin/python
# -*- coding: utf-8 -*-
"""
Fonctions nécessaires au traitement HE et DH
"""
import cv2
import math
import numpy as np
import matplotlib.pyplot as plt
##############################################
## Scripts généraux
##############################################

def Float2BGR(I):
#Conversion d'un float (0 - 1) à nb sur 8 bits (0 - 255)
    erf=I*255
    src=erf.astype('uint8')
    return src

def BGR2Float(src):
#Conversion d'un nb sur 8 bits (0 - 255) vers un float
    a=src.astype('float64')/255
    return a

def AnalyseHisto(I):
    """Moyenne et variance de chaque canal"""
    MeanB = np.median(I[:,:,0])
    MeanG = np.median(I[:,:,1])
    MeanR = np.median(I[:,:,2])
    
    SquareB = np.sqrt(1/I[:,:,0].size*sum(sum((I[:,:,0]-MeanB)**2)))
    SquareG = np.sqrt(1/I[:,:,1].size*sum(sum((I[:,:,1]-MeanG)**2)))
    SquareR = np.sqrt(1/I[:,:,2].size*sum(sum((I[:,:,2]-MeanR)**2)))
    Mean = [MeanB,MeanG,MeanR]
    Square = [SquareB,SquareG,SquareR]
    return Mean,Square

def PlotHistogram(I):
    """Fonction qui donne l'histogramme d'une image"""
    plt.figure()
    color=('b','g','r')
    for i,col in enumerate(color):
        histr = cv2.calcHist([I],[i],None,[256],[0,256])
        plt.plot(histr,color=col)
        plt.xlim([0,256])
        plt.legend(color)
        plt.title('Histogramme des canaux RGB')
        
##############################################
## Egalisation d'histogramme
##############################################

def process_image_HE(I,vB,vG,vR):
    [[MeanB,MeanG,MeanR],[SquareB,SquareG,SquareR]]=AnalyseHisto(I)
    II = np.zeros(I.shape)
    II[:,:,0] = (I[:,:,0]-MeanB+vB*SquareB)/(2*vB*SquareB)
    II[:,:,1] = (I[:,:,1]-MeanG+vG*SquareG)/(2*vG*SquareG)
    II[:,:,2] = (I[:,:,2]-MeanR+vR*SquareR)/(2*vR*SquareR)

    III=np.clip(II,0,1)
    IV=np.uint8(III*255)
    return IV

##############################################
## Debrumage
##############################################

def DarkChannel(im,sz):
    """Determine le canal sombre de l'image""" 
    b, g, r= cv2.split(im) # Séparation des 3 canaux
    dc = cv2.min(cv2.min(r,g),b) # La couleur minimale entre le canal bleu et vert.
    for ind in range(0,3):
        dc[:,ind] = np.median(dc[:,ind], axis=0) # Médiane (MDCP)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(sz,sz))  # Elément structurant pour l'érosion
    dark = cv2.erode(dc,kernel) # Erosion de l'image en fonction de la couleur minimale 
    return dark
    # L'érosion va omettre ou à amincir les limites de la zone claire de l'image

def DarkChannelWater(im,sz):
    """Determine le canal sombre de l'image""" 
    b, g, r= cv2.split(im) # Séparation des 3 canaux
    dc = cv2.min(g,b)  # La couleur minimale entre le canal bleu et vert
    for ind in range(0,3):
        dc[:,ind] = np.median(dc[:,ind], axis=0) # Médiane (MDCP)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(sz,sz))  # Elément structurant pour l'érosion
    dark = cv2.erode(dc,kernel) # Erosion de l'image en fonction de la couleur minimale 
    return dark
    # L'érosion va omettre ou à amincir les limites de la zone claire de l'image

def AtmLight(im,dark):
    """Estimation de la lumière atmosphérique""" 
    [h,w] = im.shape[:2]
    imsz = h*w
    numpx = int(max(math.floor(imsz/100),1)) # Définition du nombre de valeurs à garder (0.1%) 
    darkvec = dark.reshape(imsz) # Façonne le tableau dark sans modification de données
    imvec = im.reshape(imsz,3)
    indices = darkvec.argsort()#Tri croissant des indices du tableau 
    indices = indices[imsz-numpx::]#Suppression des 12000 indices les plus faibles
    atmsum = np.zeros([1,3])#Initialisation du tableau (toutes les valeurs sont à 0)
    for ind in range(1,numpx):
        atmsum = atmsum + imvec[indices[ind]] #Somme des valeurs avec le + d'intensité 
    A = atmsum / numpx; #Divison de la somme par le nombre de valeurs des pixels (0.1%) 
    return A
    # math.floor : arrondit à l'entier 

def TransmissionEstimate(im,A,sz):
    omega = 0.6;
    im3 = np.empty(im.shape,im.dtype) # Initalisation du tableau correspondant à la transmission
    
    for ind in range(0,3):
        im3[:,:,ind] = im[:,:,ind]/A[0,ind] # im3 = im/A (voir formule)
    transmission = 1 - omega*DarkChannel(im3,sz) # Formule pour trouver la transmission
    return transmission
    # np.empty : renvoie un nouveau tableau de forme et de type donnés, sans initialiser les entrées

def Guidedfilter(im,p,r,eps):
    """Filtre l'image d'entrée (p) sous la direction d'une autre image (im)
    Recherche les coefficients a et b qui minimisent la différence entre la sortie q et l'entrée p"""
    #Moyennes et variances utiles pour le calcul de a et b 
    mean_I = cv2.boxFilter(im,cv2.CV_64F,(r,r))
    mean_p = cv2.boxFilter(p, cv2.CV_64F,(r,r))
    mean_Ip = cv2.boxFilter(im*p,cv2.CV_64F,(r,r))
    cov_Ip = mean_Ip - mean_I*mean_p;

    mean_II = cv2.boxFilter(im*im,cv2.CV_64F,(r,r))
    var_I   = mean_II - mean_I*mean_I

    a = cov_Ip/(var_I + eps) # calcul de a selon la formule (voir doc)
    b = mean_p - a*mean_I # calcul de b selon la formule (voir doc)
    
    mean_a = cv2.boxFilter(a,cv2.CV_64F,(r,r)) #moyenne de a
    mean_b = cv2.boxFilter(b,cv2.CV_64F,(r,r)) # moyenne de b 
   
    q = mean_a*im + mean_b; # transmission affinée 
    return q;

def TransmissionRefine(im,et): 
    gray = cv2.cvtColor(im,cv2.COLOR_BGR2GRAY); #Image en teinte de gris 
    gray = np.float64(gray)/255; 
    r = 60;
    eps = 0.0001;
    t = Guidedfilter(gray,et,r,eps);
    return t;

def Recover(im,t,A,tx =1.0):
    """Fonction servant à retrouver l'éclat""" 
    res = np.empty(im.shape,im.dtype) #Initalisation du tableau correspondant à l'éclat
    tt=np.zeros((t.shape[0],t.shape[1],3)) #Initialisation du tableau tt 
   
    #Calcul de max(t(x),t0) pour chaque canal de couleur
    tt[:,:,0]=cv2.max(t,tx)      #blue
    tt[:,:,1]=cv2.max(t,tx)      #green
    tt[:,:,2]=cv2.max(t,tx)      #red

    for ind in range(0,3):
        #Formule de J(x) = (I(x)-A/max(t(x),t0))+A
        res[:,:,ind] = (im[:,:,ind]-A[0,ind])/tt[:,:,ind] + A[0,ind]
    return res

def atm_calculation(II):
    srcc = BGR2Float(II)
    dark = DarkChannel(srcc,15)
    A = AtmLight(srcc,dark)
    return A

def water_calculation(II):
    srcc = BGR2Float(II)
    dark = DarkChannelWater(srcc,15)
    A = AtmLight(srcc,dark)
    return A

def process_image_dehaze(II,A): 
    srcc= BGR2Float(II)
    te = TransmissionEstimate(srcc,A,15)
    t = TransmissionRefine(II,te) 
    III = Recover(srcc,t,A,0.1)     
    IV = np.clip(III*255,0,255)   
    V=np.uint8(IV) 
    return V

# Il peut y avoir des messages d'erreurs du style :
"""RuntimeWarning: divide by zero encountered in divide
  im3[:,:,ind] = im[:,:,ind]/A[0,ind] # im3 = im/A (voir formule)
"""
# ils surviennent quand l'image brut ne contient quasiment pas de rouge. Ce n'est normalement pas bloquant.
