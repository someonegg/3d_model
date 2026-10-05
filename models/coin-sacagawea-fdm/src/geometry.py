"""Printable half-coin topology."""
import numpy as np
from relief import P, RADIUS

def topology(rings=P['rings'],sectors=P['sectors']):
    theta=np.arange(sectors)*2*np.pi/sectors
    r=np.arange(1,rings+1)*RADIUS/rings
    xy=np.vstack(([0,0],np.column_stack(((r[:,None]*np.cos(theta)).ravel(),
                                        (r[:,None]*np.sin(theta)).ravel()))))
    j=np.arange(sectors)
    faces=[np.column_stack((np.zeros(sectors,int),1+j,1+(j+1)%sectors))]
    for k in range(rings-1):
        a,b=1+k*sectors+j,1+k*sectors+(j+1)%sectors
        c,d=a+sectors,b+sectors
        faces.extend((np.column_stack((a,c,d)),np.column_stack((a,d,b))))
    edge=np.arange(1+(rings-1)*sectors,1+rings*sectors)
    n=len(xy)
    a,b=edge,np.roll(edge,-1)
    c,d=n+j,n+(j+1)%sectors
    faces.extend((np.column_stack((a,c,d)),np.column_stack((a,d,b)),
                  np.column_stack((np.full(sectors,n+sectors),d,c))))
    return xy,edge,np.vstack(faces)


